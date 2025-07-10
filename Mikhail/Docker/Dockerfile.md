# **Dockerfile**

Контейнер - это просто процесс (PID) на хосте.

---

### **Подготовка**

Добавить пользователя в группу `docker`:
```sh
sudo usermod -aG docker ubuntu
```

---

### **Пример Dockerfile**

```dockerfile
FROM alpine:3.18

LABEL multi.label1="value1" \
      multi.label2="value2" \
      other="value3"

STOPSIGNAL SIGINT

ENV CADDY_VERSION=2.7.6

RUN apk add --no-cache curl gnupg && \
    curl -sSL "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" | gpg --dearmor > /etc/apk/keys/caddy-stable.gpg && \
    echo "https://dl.cloudsmith.io/public/caddy/stable/alpine/v3.18/main" > /etc/apk/repositories.d/caddy-stable.conf && \
    apk add --no-cache caddy=${CADDY_VERSION} && \
    rm -rf /var/cache/apk/*

RUN adduser -D -H -s /bin/false nonroot
WORKDIR /caddy

COPY --chmod=700 ./Caddyfile /caddy/Caddyfile

USER nonroot

EXPOSE 8080/tcp
ENTRYPOINT ["/usr/bin/caddy", "run"]
```

---

### **Основные инструкции**

**FROM**
Какой базовый образ взять. Для большей безопасности можно указать хэш образа (`FROM <image>@sha256:<digest>`). Хэш выводится при `docker pull alpine:latest`.

**SHELL**
Выбор оболочки для выполнения `RUN`.

**STOPSIGNAL**
Определяет сигнал операционной системы, который будет отправлен основному процессу (PID 1) внутри контейнера при его остановке. По умолчанию Docker отправляет сигнал `SIGTERM` (15), чтобы корректно завершить процесс. Если процесс не завершается после отправки `SIGTERM`, через некоторое время (по умолчанию 10 секунд) Docker отправляет сигнал `SIGKILL` (9), который принудительно завершает процесс.

**LABEL**
Присвоение меток, либо `LABEL ver1.0` или несколько меток как в примере выше.

**RUN**
Какая команда выполнится во время сборки данного образа.

- **Кэширование зависимостей:**
`--mount=type=cache` позволяет монтировать кэш в процессе выполнения `RUN`. Это ускорит повторные сборки, так как, например, зависимости будут взяты из кэша, который хранится на хосте. Кэш не попадёт в финальный образ, но будет доступен для повторного использования.
*> **Примечание:** Опции `--mount` являются частью **BuildKit**, современного движка для сборки образов. В новых версиях Docker он включен по умолчанию.*
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```


- **Bind mounts при сборке:**
`--mount=type=bind` позволяет монтировать директорию или файл с хостовой системы в контейнер во время выполнения команды `RUN`. В отличие от `COPY`, данные не копируются в образ, а временно подключаются с хоста для процесса сборки.
```dockerfile
RUN --mount=type=bind,source=./src,target=/app/src \
    go build -o app ./src
```

- **Работа с секретами:**
`--mount=type=secret` временно монтирует секрет с хоста и не хранит его в финальном образе.
```dockerfile
RUN --mount=type=secret,id=ssh,target=/root/.ssh/id_rsa \
    git clone git@github.com:user/repo.git .
    
RUN --mount=type=secret,id=api_key,target=/run/secrets/api_key \
    export API_KEY=$(cat /run/secrets/api_key) && \
    pip install --extra-index-url https://$API_KEY@private-repo.com/packages some-package
```

**COPY**
Просто копирует файл из файловой системы хоста в файловую систему контейнера. Сначала надо указать файл с хоста, а затем путь в контейнере. Если необходимо исполнение программы/скрипта с определенными правами, лучше скопировать с их присвоением, иначе при вызове в `RUN`/`ENTRYPOINT` файл скопируется еще раз (его метаданные изменятся) и увеличит размер образа.

**ADD**
Может не просто копировать файлы, как `COPY`, но и, например, скачивать по HTTP и распаковывать архивы. Поэтому инструкция `COPY` предпочтительней при создании образов, потому что делает добавление файлов в образ более прозрачным.

**WORKDIR**
Текущий каталог при старте контейнера (если его нет, то будет создан).

**EXPOSE**
Список портов, используемых контейнеризованным процессом. Но реально порты не открываются наружу этой инструкцией, это лишь для справки тем, кто использует данный образ.

**ENTRYPOINT и CMD**
`ENTRYPOINT` — какой процесс необходимо запустить при старте контейнера и его аргументы.

При запуске `docker run <имя образа> <аргументы>`, если `Dockerfile`, на основе которого был сделан образ, не содержал `ENTRYPOINT`, то выполнится только команда, например: `docker run <имя образа> <команда в образе>`.

Команда `docker run` включает в себя `docker create` (создает контейнер) и `docker start` (запускает его).

При использовании `CMD` параметры командной строки, которые вы передаёте в момент запуска контейнера, могут перезаписать параметры, указанные в `Dockerfile`.
В случае с `ENTRYPOINT`, параметры из командной строки не могут перезаписать значения из `Dockerfile`, но будут либо игнорироваться (shell form), либо добавятся к ним (exec form). Кроме того, `CMD` и `ENTRYPOINT` могут работать вместе.

Например, следующий `Dockerfile` при запуске `docker run "image"` выведет "hello world", а `docker run "image" Docker` выведет "hello Docker".
```dockerfile
ENTRYPOINT ["echo", "hello"]
CMD ["world"]
```

---

### **Оптимизация и лучшие практики**

Для уменьшения веса образа можно:
- Добавить в `RUN` удаление кэша пакетного менеджера, например: `rm -rf /var/lib/apt/lists/*`.
- Выбрать `alpine` и при установке использовать `apk add --no-cache`. Можно также при установке создать `ENV NGINX_VERSION=номер_версии` и передать `apk add --no-cache nginx=${NGINX_VERSION}`.
- Чтобы образ быстрее собирался, можно перенести части `Dockerfile`, которые часто меняются, в конец файла (если какой-то слой изменился, то все последующие будут пересобираться).
- Чтобы образ меньше весил, можно при сборке `Dockerfile` в конце добавить экспериментальную функцию `--squash`, которая аналогична `git squash` и объединяет все слои в один (но при пересборке кэш не используется).
- Использовать `dive` для анализа слоёв, `Slim` для автоматического уменьшения размера и повышения безопасности, `strip` для удаления отладочной информации из бинаря
- Изучить рекомендации по безопасности, например, [dockle](https://github.com/goodwithtech/dockle) и https://github.com/docker/docker-bench-security.
- Конвертация docker-compose файл в манифесты kubernetes(https://docs.docker.com/compose/bridge/)
