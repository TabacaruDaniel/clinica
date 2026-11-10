from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('inregistrare/', views.inregistrare, name='inregistrare'),
    path('specialist/', views.panou_specialist, name='panou_specialist'),
    path('specialist/sedinte/', views.sedinte_viitoare, name='sedinte_viitoare'),
    path('specialist/istoric/', views.istoric_sedinte, name='istoric_sedinte'),
    path('specialist/pacient-nou/', views.pacient_nou, name='pacient_nou'),
    path('specialist/programeaza/', views.programeaza_sedinta, name='programeaza_sedinta'),
    path('asistent/', views.panou_asistent, name='panou_asistent'),
    path('asistent/pacienti/', views.asistent_pacienti, name='asistent_pacienti'),
    path('asistent/pacienti/<int:pk>/leaga/', views.asistent_leaga_alege, name='asistent_leaga_alege'),
    path('asistent/pacienti/<int:pk>/leaga/<int:utilizator_pk>/', views.asistent_leaga_confirma,
         name='asistent_leaga_confirma'),
    path('asistent/pacienti/nou/', views.asistent_pacient_nou, name='asistent_pacient_nou'),
    path('asistent/pacienti/<int:pk>/programeaza/', views.asistent_programeaza, name='asistent_programeaza'),
    path('asistent/orar/<int:calificare_pk>/', views.asistent_orar, name='asistent_orar'),
    path('asistent/sedinte/<int:pk>/anuleaza/', views.asistent_anuleaza, name='asistent_anuleaza'),
    path('asistent/utilizatori/', views.asistent_utilizatori, name='asistent_utilizatori'),
    path('asistent/sedinte/', views.asistent_sedinte, name='asistent_sedinte'),
    path('specialist/profil/', views.profil_specialist, name='profil_specialist'),
    path('pacient/', views.panou_pacient, name='panou_pacient'),
    path('pacient/sedinte/', views.sedintele_mele, name='sedintele_mele'),
    path('terapeuti/', views.terapeuti, name='terapeuti'),
    path('terapeuti/<int:pk>/', views.terapeut_detaliu, name='terapeut_detaliu'),
]
