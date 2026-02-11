# Rootless контейнеры в Podman

Rootless-режим в Podman позволяет запускать контейнеры без прав суперпользователя. Контейнер видит себя как «root» внутри собственного пространства, но на хосте все операции выполняются от имени непривилегированного пользователя. Это уменьшает поверхность атаки, упрощает эксплуатацию на общих серверах и соответствует принципу наименьших привилегий.

## Механизмы, делающие rootless возможным

*   **User namespaces**: внутри контейнера UID 0 отображается в диапазон UID/GID пользователя на хосте. Для этого используются поддиапазоны из `/etc/subuid` и `/etc/subgid`.
*   **Сеть**: применяется userspace-стек slirp4netns. Он обеспечивает NAT и проброс портов без манипуляций с iptables/nftables ядра.
*   **Файловая система**: для слоёв образов используется fuse-overlayfs, работающий в пространстве пользователя.
*   **Cgroups v2**: ограничения ресурсов поддерживаются, если ядро и политики делегирования позволяют управлять поддеревом cgroup для пользователя.

## Rootful vs rootless в Podman

| Аспект | Rootful | Rootless |
| :--- | :--- | :--- |
| **Привилегии** | Доступ к системным ресурсам | Без прав суперпользователя |
| **Сеть** | Нативный netns, прямой iptables | slirp4netns, userspace NAT |
| **Порты <1024** | Доступны | Недоступны напрямую |
| **Storage driver** | overlayfs | fuse-overlayfs |
| **Cgroups** | Полный контроль | Ограничено политикой делегирования |
| **Тома** | Любые пути | Только доступные пользователю |

## Базовая проверка и подготовка

Убедитесь, что для пользователя выделены поддиапазоны UID/GID:

```bash
grep "$USER" /etc/subuid /etc/subgid || echo "Добавьте строки вида: $USER:100000:65536"
```

Проверьте, что Podman распознаёт rootless-окружение:

```handlebars
podman info --format "{{.Host.Security.Rootless}}"
podman info --format "driver={{.Store.GraphDriverName}} network={{.Host.NetworkBackend}}"
```

Инициализируйте окружение (после изменения конфигурации):

```perl
podman system migrate
```

## Запуск и сеть

Пример запуска веб-сервера с публикацией порта выше 1024:

```handlebars
podman run --rm -d --name web -p 8080:80 docker.io/library/nginx:alpine
podman ps --format "{{.Names}} -> {{.Ports}}"
```

Порты ниже 1024 в rootless-режиме недоступны напрямую. Используйте высокие порты или фронтенд-прокси на хосте, доступный пользователю.

Проверка сетевой изоляции:

```bash
podman exec web ip addr
podman port web
```

## Работа с томами и правами

При монтировании каталогов учитывайте отображение UID/GID. Вариант с сохранением идентичности пользователя внутри контейнера:

```haskell
podman run --rm -it 
  --userns=keep-id 
  -v $PWD/data:/app/data:Z 
  alpine sh -c "id && ls -ln /app/data"
```

Флаг `--userns=keep-id` облегчает работу с файлами без лишних `chown`, но не отменяет общие правила user namespaces.

## Ограничение ресурсов и cgroups v2

При активном cgroups v2 и корректной делегации можно задавать лимиты:

```bash
podman run --rm -d --name cpu-demo --cpus=0.5 --memory=256m alpine sleep 1000
podman stats cpu-demo
```

Если ядро или политика не позволяют делегирование, лимиты могут игнорироваться — проверьте вывод `podman info` и логи.

## Rootless как пользовательские сервисы systemd

Чтобы контейнеры запускались в user-сессии без входа в систему:

```sql
loginctl enable-linger $USER
podman run -d --name web --restart=always -p 8080:80 nginx:alpine
podman generate systemd --user --name web --files
systemctl --user enable --now container-web.service
```
