# Podman vs Docker: сходства и различия

Подходы Docker и Podman к контейнерам сходятся на уровне стандартов, но заметно расходятся в архитектуре и моделях безопасности. Оба поддерживают OCI-образы и OCI-runtime, умеют работать с теми же Registry, читают Dockerfile и предоставляют схожие CLI-команды, что делает миграцию типовых рабочих процессов относительно простой.

## Ключевые различия архитектуры

| Критерий | Docker | Podman |
| :--- | :--- | :--- |
| **Демон** | Централизованный docker daemon | Без демона; процессы контейнеров управляются напрямую через conmon |
| **Runtime** | containerd + runc | conmon + crun/runc |
| **Rootless** | Поддерживается, но изначально был дополнением | Из коробки и с упором на rootless-модель |
| **Сеть** | Собственная libnetwork | Netavark/Aardvark (v4+), ранее CNI |
| **Интеграция с systemd** | Управление через демон; пер-контейнерные unit-файлы — вручную/скриптами | Генерация unit-файлов: `podman generate systemd` |
| **Compose** | docker compose (официальный плагин v2) | podman-compose (сообщество), совместимость зависит от сценария |
| **K8s-интеграция** | Экспорт манифестов не встроен | `podman generate kube` / `podman play kube` |

Отсутствие демона в Podman упрощает модель доверия: нет долговременно работающего root-процесса, а контейнеры принадлежат пользователю, их легко привязать к user.slice в systemd. Docker, напротив, концентрирует управление в демон, что упрощает единый контроль, логирование и API, но требует внимательного отношения к безопасности демона.

## Безопасность и изоляция

Под Linux Podman часто сочетается с SELinux, user namespaces и rootless-режимом по умолчанию, что снижает потенциальный ущерб при компрометации контейнера. Docker также поддерживает rootless и профили seccomp/AppArmor, но исторически чаще использовался в root-режиме. В корпоративных дистрибутивах семейства RHEL/CentOS/AlmaLinux комбинация Podman+SELinux считается практикой по умолчанию.

## Совместимость CLI: соответствия команд

Ниже — типовая «механическая» замена. Во многих случаях можно заменить `docker` на `podman` без изменений флагов.

```applescript
# Запуск контейнера
docker run -d --name web -p 8080:80 nginx
podman run -d --name web -p 8080:80 nginx

# Сборка образа
docker build -t app:1.0 .
podman build -t app:1.0 .

# Работа с реестром
docker login registry.example.com
podman login registry.example.com

docker push registry.example.com/team/app:1.0
podman push registry.example.com/team/app:1.0

# Инспекция, процессы, логи
docker ps -a
podman ps -a

docker logs -f web
podman logs -f web

docker inspect web
podman inspect web
```

Compose-проекты нередко запускаются под Podman через `podman-compose`, но поддержка полного спектра возможностей спецификации может отличаться. Альтернативный путь для Podman — группировать контейнеры в «поды», близкие по идее к Kubernetes Pod.

## Сеть, тома и хранение образов

*   **Сеть**: у Docker — мосты и overlay через libnetwork; у Podman v4 — Netavark и встроенный DNS Aardvark. Команды похожи: `network create/ls/inspect`.
*   **Тома**: оба поддерживают bind-mount и managed volumes. Для rootless в Podman точки монтирования и хранилище образов располагаются в `$HOME` пользователя, что упрощает многоарендность на одном хосте.
*   **Производительность**: crun в связке с Podman обычно стартует контейнеры быстрее runc; в Docker по умолчанию runc, но возможна замена.

## Выбор инструмента в контексте платформ

*   **Linux-серверы с усиленными политиками и systemd-юнитами на контейнер**: Podman облегчает эксплуатацию без демона и с генерацией unit-файлов.
*   **Активное использование Compose и устоявшаяся экосистема плагинов/инструментов**: Docker предоставляет предсказуемый набор возможностей.
*   **macOS/Windows**: оба используют виртуальные машины; Docker Desktop предлагает зрелый UX, у Podman доступны `podman machine` и Podman Desktop.
