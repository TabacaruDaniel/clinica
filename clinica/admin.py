from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Medic, Medicament, Pacient, PlanTratament,
    PozitieReteta, Programare, Specializare, Utilizator,
)

# Utilizator uses Django's ready-made user admin (password hashing, permissions, etc.)
admin.site.register(Utilizator, UserAdmin)

@admin.register(Specializare)
class SpecializareAdmin(admin.ModelAdmin):
    search_fields = ['nume']

@admin.register(Medic)
class MedicAdmin(admin.ModelAdmin):
    list_display = ['nume', 'prenume', 'email', 'telefon']
    search_fields = ['nume', 'prenume', 'email']
    filter_horizontal = ['specializari']   # nicer widget for many-to-many

@admin.register(Pacient)
class PacientAdmin(admin.ModelAdmin):
    list_display = ['nume', 'prenume', 'data_nasterii', 'email']
    search_fields = ['nume', 'prenume', 'email']

@admin.register(Programare)
class ProgramareAdmin(admin.ModelAdmin):
    list_display = ['data_ora', 'pacient', 'medic', 'status']
    list_filter = ['status', 'medic']
    date_hierarchy = 'data_ora'

@admin.register(Medicament)
class MedicamentAdmin(admin.ModelAdmin):
    list_display = ['denumire', 'forma', 'concentratie']
    search_fields = ['denumire']

# Prescription lines are edited inside their treatment plan
class PozitieRetetaInline(admin.TabularInline):
    model = PozitieReteta
    extra = 1

@admin.register(PlanTratament)
class PlanTratamentAdmin(admin.ModelAdmin):
    list_display = ['diagnostic', 'pacient', 'medic', 'data_inceput', 'data_sfarsit']
    list_filter = ['medic']
    inlines = [PozitieRetetaInline]
