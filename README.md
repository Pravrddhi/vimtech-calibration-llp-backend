# Vimtech Calibration Backend

Django REST API for username/password authentication with JWT tokens and
database-backed user roles.

## Requirements

- Python 3.10+
- pip

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The local `.env` file uses SQLite by default and is excluded from version
control. To use MySQL, install the dependencies from `requirements.txt`,
create a database, and update the database variables in `.env` before running
migrations:

Set `DJANGO_SECRET_KEY`, set `DJANGO_DEBUG=False`, configure
`DJANGO_ALLOWED_HOSTS`, and set `CORS_ALLOWED_ORIGINS` to the frontend origins.
Use a dedicated MySQL user and keep its credentials in a secret manager or
environment variables.

For local troubleshooting, database SQL logging can be enabled with
`DB_QUERY_LOGGING=true` while `DJANGO_DEBUG=True`. Query logs may include
sensitive values; logging remains disabled in production.

When `DJANGO_DEBUG=True`, API request metadata is written to
`dev_logs/api-YYYY-MM-DD.log`. Request and response bodies, query strings, and
authorization headers are deliberately excluded to avoid logging credentials
or tokens. Authentication success/failure events and API processing errors
are written to `dev_logs/app-YYYY-MM-DD.log`; these records do not include
passwords or JWTs. Both development log types are ignored by Git. With
`DJANGO_DEBUG=False`, application events are written to the process console
instead of local files.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/docs/` | Interactive Swagger UI |
| `GET` | `/api/schema/` | OpenAPI schema |
| `POST` | `/api/login/` | Authenticate and return access/refresh JWTs |
| `GET` | `/api/users/check-username/?username=<username>` | Check username availability (active application admins only) |
| `POST` | `/api/users/` | Create a user (active application admins only) |
| `GET` | `/api/userdetails/` | Return the authenticated user's profile and role |
| `POST` | `/api/userdetails/change-password/` | Change the authenticated user's password |
| `POST` | `/api/token/refresh/` | Rotate a refresh token and return a new access token |
| `POST` | `/api/token/verify/` | Verify a submitted JWT |

Public registration is disabled. User creation requires an active account
with `user_type=admin` and `is_staff=True`. Creating another application
admin additionally requires Django superuser privileges. Password changes
revoke all outstanding refresh tokens for the user.

After creating the initial Django superuser, assign its application role:

```bash
python manage.py shell
```

```python
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.get(username="YOUR_SUPERUSER_USERNAME")
user.user_type = User.UserType.ADMIN
user.save(update_fields=["user_type"])
```

## Tests and checks

```bash
python manage.py check
python manage.py test
```