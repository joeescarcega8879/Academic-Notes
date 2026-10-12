"""Señales públicas de ``grades`` para que otras apps (como ``quizzes``) reaccionen sin que ``grades`` dependa de ellas."""

from django.dispatch import Signal

# Se envía al validar una actividad que se va a publicar. Argumento: ``activity``.
# Un receptor puede vetar la publicación lanzando ``ValidationError`` (p. ej., un quiz sin preguntas).
activity_publishing = Signal()

# Se envía por cada actividad copiada al duplicar un grupo, dentro de la misma transacción.
# Argumentos: ``source`` (la original) y ``clone`` (la copia, ya guardada y en borrador).
activity_cloned = Signal()
