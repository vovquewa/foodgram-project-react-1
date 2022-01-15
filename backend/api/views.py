from datetime import datetime as dt
from urllib.parse import unquote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import F, Sum
from django.http.response import HttpResponse

from djoser.views import UserViewSet as DjoserUserViewSet

from recipes.models import AmountIngredient, Ingredient, Recipe, Tag

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from . import conf
from .mixins import AddDelViewMixin
from .paginators import PageLimitPagination
from .permissions import AdminOrReadOnly, AuthorStaffOrReadOnly
from .serializers import (IngredientSerializer, RecipeSerializer,
                          ShortRecipeSerializer, TagSerializer,
                          UserSerializer, UserSubscribeSerializer)
from .services import incorrect_layout

User = get_user_model()


class UserViewSet(DjoserUserViewSet, AddDelViewMixin):
    """
    ViewSet для работы с пользователми - вывод таковых,
    регистрация.
    Для авторизованных пользователей —
    возможность подписаться на автора рецепта.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    pagination_class = PageLimitPagination
    add_serializer = UserSubscribeSerializer

    @action(methods=conf.ACTION_METHODS, detail=True)
    def subscribe(self, request, id):
        """
        Создаёт либо удалет объект связи между запрашивающим
        и запрошенным пользователями.
        Вызов метода через url: */user/<int:id>/subscribe/.
        """
        return self.add_del_obj(id, conf.SUBSCRIBE_M2M)

    @action(methods=('get',), detail=False)
    def subscriptions(self, request):
        """
        Выводит список пользоваетелей
        на которых подписан запрашивающй пользователь
        Вызов метода через url: */user/<int:id>/subscribtions/.
        """
        user = self.request.user
        if user.is_anonymous:
            return Response(status=HTTP_401_UNAUTHORIZED)
        authors = user.subscribe.all()
        pages = self.paginate_queryset(authors)
        serializer = UserSubscribeSerializer(
            pages, many=True, context={'request': request}
        )
        return self.get_paginated_response(serializer.data)


class TagViewSet(ReadOnlyModelViewSet):
    """
    ViewSet для работы с тэгами.
    Изменение и создание объектов разрешено только админам.
    """
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = (AdminOrReadOnly,)


class IngredientViewSet(ReadOnlyModelViewSet):
    """
    ViewSet для работы с игридиентами.
    Изменение и создание объектов разрешено только админам.
    """
    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer
    permission_classes = (AdminOrReadOnly,)

    def get_queryset(self):
        """
        Реализован поиск объектов по совпадение в начале назавния,
        также добавляются результаты по совпадению в середине.
        При наборе названия в неправильной раскладке - латинские символы
        преобразуются в кириллицу (для стандартной раскладки).
        Также прописные буквы преобразуются в строчные,
        так как все ингридиенты в базе записаны в нижнем регистре.
        """
        name = self.request.query_params.get(conf.SEARCH_ING_NAME)
        queryset = self.queryset
        if name:
            if name[0] == '%':
                name = unquote(name)
            else:
                name = name.translate(incorrect_layout)
            name = name.lower()
            stw_queryset = list(queryset.filter(name__startswith=name))
            cnt_queryset = queryset.filter(name__contains=name)
            stw_queryset.extend(
                [i for i in cnt_queryset if i not in stw_queryset]
            )
            queryset = stw_queryset
        return queryset


class RecipeViewSet(ModelViewSet, AddDelViewMixin):
    """
    ViewSet для работы с рецептами - вывод, создание, редактирование,
    добавление/удаление в избранное и список покупок.
    Отправка текстового файла со списком покупок.
    Для авторизованных пользователей — возможность добавить
    рецепт в избранное и в список покупок.
    Изменять рецепт может только автор или админы.
    """
    queryset = Recipe.objects.select_related('author')
    serializer_class = RecipeSerializer
    permission_classes = (AuthorStaffOrReadOnly,)
    pagination_class = PageLimitPagination
    add_serializer = ShortRecipeSerializer

    def get_queryset(self):
        queryset = self.queryset

        tags = self.request.query_params.getlist(conf.TAGS)
        if tags:
            queryset = queryset.filter(
                tags__slug__in=tags).distinct()

        author = self.request.query_params.get(conf.AUTHOR)
        if author:
            queryset = queryset.filter(author=author)

        # Следующие фильтры только для авторизованного пользователя
        user = self.request.user
        if user.is_anonymous:
            return queryset

        is_in_shopping = self.request.query_params.get(conf.SHOP_CART)
        if is_in_shopping in conf.SYMBOL_TRUE_SEARCH:
            queryset = queryset.filter(cart=user.id)
        elif is_in_shopping in conf.SYMBOL_FALSE_SEARCH:
            queryset = queryset.exclude(cart=user.id)

        is_favorited = self.request.query_params.get(conf.FAVORITE)
        if is_favorited in conf.SYMBOL_TRUE_SEARCH:
            queryset = queryset.filter(favorite=user.id)
        if is_favorited in conf.SYMBOL_FALSE_SEARCH:
            queryset = queryset.exclude(favorite=user.id)

        return queryset

    @action(methods=conf.ACTION_METHODS, detail=True)
    def favorite(self, request, pk):
        """
        Добавляет либо удалет рецепт в "избранное".
        Вызов метода через url:  */recipe/<int:pk>/favorite/.
        """
        return self.add_del_obj(pk, conf.FAVORITE_M2M)

    @action(methods=conf.ACTION_METHODS, detail=True)
    def shopping_cart(self, request, pk):
        """
        Добавляет либо удалет рецепт в "список покупок".
        Вызов метода через url:  */recipe/<int:pk>/shopping_cart/.
        """
        return self.add_del_obj(pk, conf.SHOP_CART_M2M)

    @action(methods=('get',), detail=False)
    def download_shopping_cart(self, request):
        """
        Считает сумму ингредиентов в рецептах выбранных для покупки.
        Возвращает текстовый файл со списком ингредиентов.
        Вызов метода через url:  */recipe/<int:id>/download_shopping_cart/.
        """
        user = self.request.user
        if not user.carts.exists():
            return Response(status=HTTP_400_BAD_REQUEST)
        ingredients = AmountIngredient.objects.filter(
            recipe__in=(user.carts.values('id'))
        ).values(
            ingredient=F('ingredients__name'),
            measure=F('ingredients__measurement_unit')
        ).annotate(amount=Sum('amount'))

        filename = f'{user}_shopping_list.txt'
        filepath = settings.MEDIA_ROOT / filename
        with open(filepath, 'w') as file:
            file.write(
                f'Список покупок для:\n\n{user.first_name}\n\n'
                f'{dt.now().strftime(conf.DATE_TIME_FORMAT)}\n\n'
            )
            for ing in ingredients:
                file.write(
                    f"{ing['ingredient']}: {ing['amount']} {ing['measure']}\n"
                )
            file.write(
                '\nПосчитано в Foodgram.ml\n'
            )

        shopping_list = open(filepath, 'r')
        response = HttpResponse(shopping_list, content_type='text.txt')
        response['Content-Disposition'] = f'attachment; filename={filename}'
        return response
