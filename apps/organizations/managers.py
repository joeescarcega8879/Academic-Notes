from django.db import models


class OrganizationQuerySet(models.QuerySet):
    def for_organization(self, organization):
        """Filas de ``organization``. Sin organización (None) no devuelve nada.

        Fallar cerrado es deliberado: una vista que olvide resolver la
        organización no debe filtrar datos de todos los tenants.
        """
        if organization is None:
            return self.none()
        return self.filter(organization=organization)


OrganizationManager = models.Manager.from_queryset(OrganizationQuerySet)
