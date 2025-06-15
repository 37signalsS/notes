Контейнер - это просто процесс(PID) на хосте dockerfile

Добавить пользователя в группу docker:

```sh
sudo usermod -aG docker ubuntu
```

``` dockerfile
FROM alpine:3.18

LABEL multi.label1="value1" \
      multi.label2="value2" \
      other="value3"

STOPSIGNAL SIGINT

ENV CADDY_VERSION=2.7.6

RUN apk add --no-cache curl gnupg && \
    curl -sSL "https://dl.cloudsmith.io/public/caddy/stable/gpg.key " | gpg --dearmor > /etc/apk/keys/caddy-stable.gpg && \
    echo "https://dl.cloudsmith.io/public/caddy/stable/alpine/v3.18/main " > /etc/apk/repositories.d/caddy-stable.conf && \
    apk add --no-cache caddy=${CADDY_VERSION} && \
    rm -rf /var/cache/apk/*

RUN adduser -D -H -s /bin/false nonroot
WORKDIR /caddy

COPY --chmod=700 ./Caddyfile /caddy/Caddyfile

USER nonroot

EXPOSE 8080/tcp
ENTRYPOINT ["/usr/bin/caddy", "run"]
```

- FROM  —  какой базовый образ взять. Для большей безопасности можно указать хэш образа(FROM <image>@sha256:<digest>. Хэш выводиться при docker pull alpine:latest). 

- SHELL - выбор оболочки выполнения RUN

- STOPSIGNAL - определяет сигнал операционной системы, который будет отправлен основному процессу (PID 1) внутри контейнера при его остановке. По умолчанию Docker отправляет сигнал SIGTERM(15), чтобы корректно завершить процесс. Если процесс не завершается после отправки SIGTERM, через некоторое время (по умолчанию 10 секунд) Docker отправляет сигнал SIGKILL(9), который принудительно завершает процесс.

- LABEL - присвоение меток, либо LABEL ver1.0 или несколько меток как в примере выше

- RUN   —  какая команда выполнится во время сборки данного образа. 
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```
--mount=type=cache - позволяет монтировать кэш в процесcе выполнения RUN(ускорит повторные сборки, так как,например, зависимости будут взяты из кэша которых храниться на хосте; кэш не будет в финальном образе но будет в директории на хосте для повторного использования 

```dockerfile
RUN --mount=type=bind,source=./src,target=/app/src \
    go build -o app ./src
```
--mount=type=bind - позволяет монтировать директорию или файл с хостовой системы в контейнер во время выполнения команды RUN, в отличие от COPY данные не копируются в образ а временно подключаются с хоста для процесса сборки

```dockerfile
RUN --mount=type=secret,id=ssh,target=/root/.ssh/id_rsa \
    git clone git@github.com:user/repo.git .
    
RUN --mount=type=secret,id=api_key,target=/run/secrets/api_key \
    export API_KEY=$(cat /run/secrets/api_key) && \
    pip install --extra-index-url https://$API_KEY@private-repo.com/packages some-package
```
--mount=type=secret - временно монтирует секрет с хоста и не хранит его в финальном образе

- COPY  —  просто копирует файл из файловой системы хоста в файловую систему контейнера; сначала надо указать файл с хоста, а затем путь в контейнере. Если необходимо исполнение программы/скрипта с определенными правами лучше скопировать с их присвоением, иначе при вызове в RUN/ENTRYPOINT файл скопируется еще раз(его метаданные изменились) и увеличит размер образа.

- ADD — может не просто копировать файлы, как COPY, но и, например, скачивать по http и распаковывать архивы, поэтому инструкция COPY предпочтительней при создании образов, потому что делает добавление файлов в образ более прозрачным.

- WORKDIR — текущий каталог при старте контейнера(если его нету то будет создан).

- EXPOSE — список портов, используемых контейнеризованным процессом. Но реально порты не открываются наружу ​это инструкцией, это лишь для справки тем, кто использует данный образ.

- ENTRYPOINT  —   какой процесс необходимо запустить при старте контейнера и его аргументы

При запуске docker run <имя образа> <что нужно добавить к вызову, указанному в ENTRYPOINT-образа>, если Dockerfile, на основе которого был сделан образ, не содержал ENTRYPOINT, то выполнится только команда, например: docker run <имя образа> <команда в образе>.

docker run включает в себя: docker create который создает образ и docker start который его запускает

При использовании CMD параметры командной строки, которые вы передаёте в момент запуска контейнера в командной строке, могут перезаписать параметры, указанные в Dockerfile. 
В случае с ENTRYPOINT, параметры из командной строки не могут перезаписать значения из Dockerfile, но будут либо игнорироваться (shell form), либо добавятся к ним (exec form). Кроме того, CMD и ENTRYPOINT могут работать вместе, сохраняя своё поведение.

Например, запуск docker run "image" выведет hello word, а docker run "image" Docker выведет hello Docker

``` dockerfile
ENTRYPOINT ["echo", "hello"]
CMD ["echo", "world"]
```

Также для уменьшения веса образа можно:
- добавить в RUN удаление кэша пакетного менеджера rm -rf /var/lib/apt/lists/*
- выбрать alpine и при установке использовать apk add --no-cache. Можем также при установке создать ENV NGINX_VERSION номер_версии и передать apk add --no-cache nginx=${NGINX_VERSION}
- чтобы образ быстрее собирался можно перенести части-строки  Dockerfile которая часто меняется в конец Dockerfile(если какой-то слой изменился то последующие будут пересобираться)
- чтобы образ меньше весил можно при сборке Dockerfle  в конце добавить экспериментальную функцию --squash, которая по аналогична git squash и объединяет все слои в один(но при пересборке кэш не используется)
- использовать dive для анализа слоёв и Slim для автоматического уменьшения размера и повышения безопасности
- https://github.com/goodwithtech/dockle





