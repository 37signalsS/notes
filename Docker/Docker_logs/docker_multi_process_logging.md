# Логирование в контейнерах с несколькими процессами

По умолчанию `docker logs` отслеживает только стандартные потоки (`STDOUT`, `STDERR`) процесса с **PID 1** внутри контейнера. Если вы запускаете несколько процессов, логи дочерних процессов не будут видны, если их не перенаправить.

#### Перенаправление потоков на PID 1

Простой способ — перенаправить потоки дочерних процессов на стандартные потоки процесса с PID 1. В Linux это можно сделать, используя псевдофайловую систему `/proc`.

- `/proc/1/fd/1` — стандартный вывод (STDOUT) процесса PID 1.
- `/proc/1/fd/2` — стандартный вывод ошибок (STDERR) процесса PID 1.

**Пример `entrypoint.sh`:**
```bash
#!/bin/bash

# Запускаем первый процесс в фоне, перенаправляя его потоки
./my-app-1 > /proc/1/fd/1 2>/proc/1/fd/2 &

# Запускаем второй процесс в фоне
./my-app-2 > /proc/1/fd/1 2>/proc/1/fd/2 &

# Ждем завершения всех фоновых процессов
wait -n
```
> **Примечание:** Этот метод прост, но не решает проблему "зомби-процессов" и сложен в управлении.

#### Использование супервизора процессов 

Более надежное и правильное решение — использовать легковесный менеджер процессов, такой как **`supervisord`**. Он запускается как PID 1, управляет дочерними процессами и корректно собирает их логи.

**Шаги:**

1.  Установите `supervisor` в ваш образ (`apt-get install supervisor` или `pip install supervisor`).
2.  Создайте конфигурационный файл `supervisord.conf`.
3.  Запустите `supervisord` в качестве основной команды (`CMD` или `ENTRYPOINT`).

**Пример `supervisord.conf`:**

```ini
[supervisord]
nodaemon=true ; Запускает supervisord в основном потоке, что необходимо для Docker

[program:app1]
command=/usr/bin/my-app-1
autostart=true
autorestart=true
stdout_logfile=/dev/stdout ; Перенаправить stdout в stdout supervisord
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr ; Перенаправить stderr в stderr supervisord
stderr_logfile_maxbytes=0

[program:app2]
command=/usr/bin/my-app-2
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
```

**Пример Dockerfile:**

```dockerfile
FROM ubuntu:22.04

# ... установка зависимостей и копирование файлов приложения ...
RUN apt-get update && apt-get install -y supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY my-app-1 /usr/bin/my-app-1
COPY my-app-2 /usr/bin/my-app-2

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```
