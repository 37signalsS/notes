# Dockerfile: Лучшие практики для PostgreSQL

Официальный Docker-образ `postgres` предоставляет специальный механизм для инициализации базы данных при первом запуске контейнера. Любые файлы с расширениями `.sh`, `.sql` или `.sql.gz`, помещенные в каталог `/docker-entrypoint-initdb.d/` внутри контейнера, будут выполнены в алфавитном порядке при его создании.
```dockerfile
FROM postgres:15
COPY init.sql /docker-entrypoint-initdb.d/
```
