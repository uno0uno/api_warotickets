"""
Template de confirmacion para solicitudes de acceso como organizador.
Sigue la misma estructura visual que magic_link_template.py.
"""


def get_lead_confirmation_template(name: str, email: str) -> str:
    """
    Genera el HTML del correo de confirmacion para una solicitud de organizador.

    Args:
        name: Nombre del solicitante (puede ser el prefix del email si no se captura)
        email: Email del solicitante

    Returns:
        HTML string listo para enviar via AWS SES
    """
    display_name = name if name else email.split('@')[0]

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Solicitud recibida - WaRo Tickets</title>
</head>
<body style="font-family: Arial, sans-serif; color: black; margin: 0; padding: 0; text-align: left;">
    <div style="font-family: Arial, sans-serif; max-width: 600px; padding: 20px;">

        <p>Hola {display_name},</p>

        <p>Recibimos tu solicitud para acceder como organizador en WaRo Tickets. Gracias por tu interes.</p>

        <p>Nuestro equipo revisara tu informacion y se pondra en contacto contigo en los proximos dias habiles para activar tu cuenta y darte acceso a la plataforma.</p>

        <p>Si tienes alguna pregunta urgente, no dudes en responder a este correo.</p>

        <p>Hasta pronto,<br>El equipo de WaRo Tickets</p>

        <br>
        ----<br>
        Anderson Arevalo<br>
        Fundador WaRo Tickets<br>
        Direccion: <a href="https://maps.app.goo.gl/CjipiqrV2iYUx2fa8">Calle 39F # 68F - 66 Sur</a><br>
        Bogota, D.C, Colombia<br>
        Tel: 3142047013<br>
        Correo: <a href="mailto:anderson.arevalo@warotickets.com">anderson.arevalo@warotickets.com</a><br>
        Tu evento, tu publico, tu exito.

    </div>
</body>
</html>""".strip()


def get_lead_confirmation_subject() -> str:
    return "Recibimos tu solicitud - WaRo Tickets"
