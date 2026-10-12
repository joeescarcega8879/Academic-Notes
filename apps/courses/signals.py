"""Señales propias de ``courses`` para que otras apps reaccionen sin que ``courses`` dependa de ellas."""

from django.dispatch import Signal

# Se envía tras duplicar un grupo para un nuevo ciclo, dentro de la misma transacción.
# Argumentos: ``source`` (grupo original) y ``clone`` (grupo nuevo, ya guardado).
# Quien guarde contenido propio del grupo (esquema de evaluación, evaluaciones…) lo copia aquí.
course_cloned = Signal()
