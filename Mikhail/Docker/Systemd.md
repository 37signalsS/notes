Условие:  
Контейнер на базе ubuntu:22.04, в котором хочешь использовать systemd, потому что:

- там запускается несколько сервисов  
- хочешь юниты, логирование через journalctl и `target`-зависимости

Dockerfile:

```
FROM ubuntu:22.04
RUN apt update && apt install -y systemd
CMD ["/sbin/init"]
```

Контейнер запускается. Но:

- systemctl внутри контейнера зависает или падает
- сервисы не стартуют
- journalctl выдаёт: Failed to create /run/systemd/notify: Protocol not supported

1. Docker не предназначен для запуска полноценного init-сервиса

- systemd требует PID 1, работу cgroups, tmpfs, правильный init-режим  
- Docker по умолчанию отключает многие возможности, нужные systemd:  
  • /sys/fs/cgroup  
  • tmpfs /run  
  • CAP_SYS_ADMIN  
  • --privileged

1. Для запуска systemd inside Docker:

```
   docker run -d --privileged \
     --tmpfs /run --tmpfs /run/lock \
     -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
     myimage:latest
```


2. Лучше: не делать так вообще  
   Вместо systemd — использовать:
   - supervisord, tini, s6-overlay, runit — как минимальный init  