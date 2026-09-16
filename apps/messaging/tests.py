from django.test import RequestFactory, TestCase
from django.contrib.auth.models import AnonymousUser

from apps.accounts.models import User, StudentProfile, ProfessorProfile
from apps.messaging.context_processors import unread_messages
from apps.messaging.models import Conversation, Message
from apps.subjects.models import Subject, Enrollment


def conv_items(html):
    """Devuelve el HTML de cada .conv-item renderizado."""
    import re
    return re.findall(r'<a class="conv-item.*?</a>', html, re.S)


class MessagingAccessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.prof = User.objects.create_user(
            username='prof1', email='prof1@test.local', password='Pass123!',
            role='professor', first_name='Ana', last_name='Perez',
        )
        ProfessorProfile.objects.create(user=cls.prof, department='Matematicas')

        cls.other_prof = User.objects.create_user(
            username='prof2', email='prof2@test.local', password='Pass123!',
            role='professor', first_name='Bruno', last_name='Diaz',
        )
        ProfessorProfile.objects.create(user=cls.other_prof, department='Fisica')

        cls.student = User.objects.create_user(
            username='alum1', email='alum1@test.local', password='Pass123!',
            role='student', first_name='Sofia', last_name='Lopez',
        )
        StudentProfile.objects.create(user=cls.student, program='ISC', semester=5, enrollment_number='A0001')

        cls.other_student = User.objects.create_user(
            username='alum2', email='alum2@test.local', password='Pass123!',
            role='student', first_name='Diego', last_name='Ruiz',
        )
        StudentProfile.objects.create(user=cls.other_student, program='ISC', semester=3, enrollment_number='A0002')

        cls.subject = Subject.objects.create(name='Calculo', code='CAL1', professor=cls.prof)
        cls.subject2 = Subject.objects.create(name='Fisica', code='FIS1', professor=cls.other_prof)

        cls.enrollment = Enrollment.objects.create(student=cls.student, subject=cls.subject)
        cls.other_enrollment = Enrollment.objects.create(student=cls.other_student, subject=cls.subject2)

    def conv(self):
        return Conversation.objects.get(student=self.student, subject=self.subject)

    # --- signal ---

    def test_signal_crea_conversacion_al_inscribir(self):
        self.assertEqual(Conversation.objects.count(), 2)
        self.assertTrue(Conversation.objects.filter(subject=self.subject, student=self.student).exists())

    # --- acceso ---

    def test_profesor_lista_200(self):
        self.client.force_login(self.prof)
        r = self.client.get('/mensajes/')
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'mensajes.html')

    def test_alumno_lista_200(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get('/mensajes/').status_code, 200)

    def test_anonimo_redirige_a_login(self):
        r = self.client.get('/mensajes/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_detalle_participante_200(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get('/mensajes/%s/' % self.conv().pk).status_code, 200)

    def test_detalle_ajeno_404(self):
        self.client.force_login(self.student)
        ajeno = Conversation.objects.get(student=self.other_student, subject=self.subject2)
        self.assertEqual(self.client.get('/mensajes/%s/' % ajeno.pk).status_code, 404)

    # --- envio ---

    def test_post_crea_mensaje(self):
        self.client.force_login(self.student)
        conv = self.conv()
        r = self.client.post('/mensajes/%s/enviar/' % conv.pk, {'body': 'Hola profe'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Message.objects.filter(conversation=conv).count(), 1)
        self.assertEqual(Message.objects.get(conversation=conv).sender, self.student)

    def test_post_con_body_vacio_no_crea(self):
        self.client.force_login(self.student)
        conv = self.conv()
        self.client.post('/mensajes/%s/enviar/' % conv.pk, {'body': '   '})
        self.assertEqual(Message.objects.filter(conversation=conv).count(), 0)

    # --- no leidos ---

    def test_unread_count_llega_al_contexto(self):
        Message.objects.create(conversation=self.conv(), sender=self.prof, body='Hola')
        self.client.force_login(self.student)
        r = self.client.get('/mensajes/')
        self.assertIn('unread_count', r.context)
        self.assertEqual(r.context['unread_count'], 1)

    def test_badge_se_renderiza_en_el_sidebar(self):
        Message.objects.create(conversation=self.conv(), sender=self.prof, body='Hola')
        self.client.force_login(self.student)
        self.assertContains(self.client.get('/mensajes/'), 'nav-badge')

    def test_abrir_conversacion_marca_como_leido(self):
        Message.objects.create(conversation=self.conv(), sender=self.prof, body='Hola')
        self.client.force_login(self.student)
        self.client.get('/mensajes/%s/' % self.conv().pk)
        self.assertEqual(Message.objects.filter(read_at__isnull=True).count(), 0)

    def test_anonimo_no_cuenta_no_leidos(self):
        request = RequestFactory().get('/login/')
        request.user = AnonymousUser()
        self.assertEqual(unread_messages(request), {'unread_count': 0})

    # --- contraparte (bug: counterpart(user) no se puede llamar sin argumentos en template) ---

    def test_alumno_ve_al_profesor_en_la_lista(self):
        self.client.force_login(self.student)
        items = conv_items(self.client.get('/mensajes/').content.decode())
        self.assertTrue(items, 'no se renderizo ningun .conv-item')
        self.assertIn('Ana Perez', items[0])
        self.assertNotIn('alum1@test.local', items[0])
        self.assertIn('>AP<', items[0])

    def test_profesor_ve_al_alumno_en_la_lista(self):
        self.client.force_login(self.prof)
        items = conv_items(self.client.get('/mensajes/').content.decode())
        self.assertTrue(items, 'no se renderizo ningun .conv-item')
        self.assertIn('Sofia Lopez', items[0])
        self.assertIn('>SL<', items[0])

    # --- sidebar ---

    def test_sidebar_marca_mensajes_en_el_detalle(self):
        self.client.force_login(self.student)
        r = self.client.get('/mensajes/%s/' % self.conv().pk)
        self.assertContains(r, 'is-active')
