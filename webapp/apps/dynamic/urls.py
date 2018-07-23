from django.conf.urls import url

from .views import (dynamic_landing, dynamic_behavioral,
                    behavior_results, edit_dynamic_behavioral, elastic_results,
                    dynamic_elasticities, edit_dynamic_elastic)


urlpatterns = [
    url(r'^(?P<pk>\d+)/', dynamic_landing, name='dynamic_landing'),
    url(r'^behavioral/(?P<pk>\d+)/', dynamic_behavioral,
        name='dynamic_behavioral'),
    url(r'^behavioral/edit/(?P<pk>\d+)/', edit_dynamic_behavioral,
        name='edit_dynamic_behavioral'),
    url(r'^macro/edit/(?P<pk>\d+)/', edit_dynamic_elastic,
        name='edit_dynamic_elastic'),
    url(r'^macro/(?P<pk>\d+)/', dynamic_elasticities,
        name='dynamic_elasticities'),
    url(r'^macro_results/(?P<pk>\d+)/', elastic_results,
        name='elastic_results'),
    url(r'^behavior_results/(?P<pk>\d+)/', behavior_results,
        name='behavior_results'),
]
