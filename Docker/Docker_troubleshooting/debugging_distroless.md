# Отладка контейнеров без shell (distroless)

`Distroless`-образы — лучшая практика безопасности, но стандартная отладка через `docker exec -it <container> /bin/sh` в них не работает.

### `docker exec` с другим пользователем

Если в образе есть shell, но он недоступен текущему пользователю, попробуйте зайти как `root`:

```sh
docker exec -it --user root <container_name> /bin/sh
```

### Эфемерный отладочный контейнер (рекомендуемый способ)

Запуск временного контейнера с полным набором утилит в пространствах имён целевого контейнера.

*   **Анализ сети:**

    ```sh
    # nicolaka/netshoot содержит множество сетевых утилит (ss, tcpdump и т.д.)
    docker run -it --rm --network=container:<target_container_name> nicolaka/netshoot
    ```

*   **Анализ процессов:**

    ```sh
    # Позволяет видеть процессы целевого контейнера (ps, top, strace)
    docker run -it --rm --pid=container:<target_container_name> alpine
    ```

### Копирование файлов с помощью `docker cp`

Для анализа логов или конфигураций просто скопируйте их на хост:

```sh
docker cp <container_name>:/path/to/file /local/path/
```

### Использование `docker debug`

Эта команда (доступна в Docker Desktop версии 4.27.0 и выше) является современным решением для отладки. Она создает копию контейнера, но с возможностью переопределить `entrypoint` или добавить инструменты.

```sh
# Создаст копию контейнера my-app и запустит в ней /bin/sh из образа alpine
docker debug my-app -it --image=alpine --entrypoint=/bin/sh
```
