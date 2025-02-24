"""Модуль содержит дополнительные классы
для настройки основных классов приложения.
"""

from django.shortcuts import get_object_or_404

from rest_framework.response import Response
from rest_framework.status import (HTTP_201_CREATED, HTTP_204_NO_CONTENT,
                                   HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED)

from . import conf


class AddDelViewMixin:
    """
    Добавляет во Viewset дополнительные методы.

    Содержит метод добавляющий/удаляющий объект связи
    Many-to-Many между моделями.
    Требует определения атрибута `add_serializer`.

    Example:
        class ExampleViewSet(ModelViewSet, AddDelViewMixin)
            ...
            add_serializer = ExamplSerializer

            def example_func(self, request, **kwargs):
                ...
                obj_id = ...
                return self.add_del_obj(obj_id, relation.M2M)
    """

    add_serializer = None

    def _get_relation(self, relation):
        """Ищет связь через менеджер `model.many-to-many`.

        Args:
            relation (model.ManyRelatedManager):
                Менеджер указанной модели управляющий требуемой связью.

        Raises:
            AttributeError: Если у модели нет указанного менеджера.
        Returns:
            model.ManyRelatedManager: Найденый менеджер.
        """
        match relation:
            case conf.SUBSCRIBE_M2M:
                return self.request.user.subscribe
            case conf.FAVORITE_M2M:
                return self.request.user.favorites
            case conf.SHOP_CART_M2M:
                return self.request.user.carts
            case _:
                raise AttributeError(f'Relation {relation} not found')


    def add_del_obj(self, obj_id, relation):
        """Добавляет/удаляет связь через менеджер `model.many-to-many`.

        Доступные для работы менеджеры-М2М должны быть внесены в словарь
        `menegers` откуда будут вызываться в зависимости от переданного ключа.

        Args:
            obj_id (int):
                id обЪекта, с которым требуется создать/удалить связь.
            relation (model.ManyRelatedManager):
                Менеджер указанной модели управляющий требуемой связью.

        Returns:
            Responce: Статус подтверждающий/отклоняющий действие.
        """
        assert self.add_serializer is not None, (
            f'{self.__class__.__name__} should include '
            'an `add_serializer` attribute.'
        )

        user = self.request.user
        if user.is_anonymous:
            return Response(status=HTTP_401_UNAUTHORIZED)

        relation = self._get_relation(relation)
        obj = get_object_or_404(self.queryset, id=obj_id)
        serializer = self.add_serializer(
            obj, context={'request': self.request}
        )
        obj_exist = relation.filter(id=obj_id).exists()

        if (self.request.method in conf.ADD_METHODS) and not obj_exist:
            relation.add(obj)
            return Response(serializer.data, status=HTTP_201_CREATED)

        if (self.request.method in conf.DEL_METHODS) and obj_exist:
            relation.remove(obj)
            return Response(status=HTTP_204_NO_CONTENT)
        return Response(status=HTTP_400_BAD_REQUEST)
