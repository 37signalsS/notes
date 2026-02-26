# Podman: Основные команды

## Определения

**Podman (Pod Manager)** — инструмент управления контейнерами OCI-совместимыми контейнерами. Является заменой Docker с архитектурой без демона.

## Установка

В RHEL и подобных дистрибутивах Podman устанавливается через модули:

```bash
# Поиск модуля
dnf module list | grep container

# Включение модуля (обычно container-tools)
dnf module enable container-tools

# Установка
dnf module install container-tools
```

## Основные концепции

### Работа с образами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| **Поиск образов** | `podman search <образ>` | Поиск образов в реестрах |
| **Скачивание** | `podman pull <образ>` | Скачать образ из реестра |
| **Список образов** | `podman images` | Показать локальные образы |
| **Тегирование** | `podman tag <образ> <новое_имя>` | Добавить тег (например, для пуша в локальный реестр) |
| **Инспекция** | `podman inspect <образ>` | Показать метаданные образа (порты, переменные, пользователь) |
| **Удаление** | `podman rmi <образ>` | Удалить локальный образ |

### Работа с контейнерами

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| **Запуск** | `podman run -d --name <имя> -p <порт_хост>:<порт_контейнер> <образ>` | Создать и запустить контейнер |
| **Список (работающие)** | `podman ps` | Показать запущенные контейнеры |
| **Список (все)** | `podman ps -a` | Показать все контейнеры |
| **Логи** | `podman logs <контейнер>` | Показать логи контейнера |
| **Выполнить команду** | `podman exec -it <контейнер> <команда>` | Выполнить команду в работающем контейнере |
| **Остановка** | `podman stop <контейнер>` | Остановить контейнер |
| **Запуск** | `podman start <контейнер>` | Запустить остановленный контейнер |
| **Удаление** | `podman rm <контейнер>` | Удалить контейнер |

### Практические примеры

**Запуск веб-сервера Nginx:**

```bash
# Запуск в фоновом режиме с пробросом портов
podman run -d --name nginx -p 8080:80 nginx

# Проверка работы
curl http://localhost:8080

# Просмотр логов
podman logs nginx

# Вход в контейнер
podman exec -it nginx /bin/sh
```

**Использование Volume:**

```bash
# Монтирование директории
podman run -d --name myapp -v /home/user/data:/data myimage

# Ключ -Z для SELinux (RHEL)
podman run -d --name myapp -v /home/user/data:/data:Z myimage
```

## Работа с локальным реестром

Для экономии трафика и работы в изолированных сетях можно поднять локальный реестр образов.

**Запуск реестра:**

```bash
# Создание директории для хранения образов
mkdir -p ~/registry

# Запуск контейнера с реестром
podman run -d --name registry \
  -p 5000:5000 \
  -v ~/registry:/var/lib/registry:z \
  registry
```

**Настройка политики доверия (без HTTPS):**

В файле `/etc/containers/registries.conf`:

```toml
[[registry]]
location = "localhost:5000"
insecure = true
```

**Загрузка образа в локальный реестр:**

```bash
# Скачивание официального образа
podman pull docker.io/library/nginx

# Тегирование для локального реестра
podman tag docker.io/library/nginx localhost:5000/nginx

# Загрузка
podman push localhost:5000/nginx
```

**Использование Skopeo для копирования:**

```bash
# Копирование образа из Docker Hub в локальный реестр
skopeo copy docker://docker.io/library/httpd docker://localhost:5000/httpd
```

## Дополнительная информация

### Cockpit интеграция

Podman интегрирован в **Cockpit** — веб-интерфейс для администрирования Linux-серверов.

После установки модуля `container-tools` в Cockpit появляется вкладка **Podman Containers**, где можно:
- Управлять контейнерами (запуск, остановка, удаление)
- Просматривать логи
- Подключаться к контейнеру через терминал
- Создавать и управлять Pod'ами

Для активации запустите сервис:
```bash
systemctl enable --now cockpit.socket
```

Доступ через: `https://<сервер>:9090`

## Дополнительная информация

- **Архитектура:** [Daemonless архитектура Podman](./podman_daemonless_architecture.md)
- **Rootless режим:** [Rootless режим в Podman](./podman_rootless.md)
- **Сравнение с Docker:** [Podman vs Docker](./podman_vs_docker.md)
- **Buildah (сборка образов):** [Альтернативные среды выполнения](./alternatives_crio_containerd.md)
- **Skopeo (работа с реестрами):** [Альтернативные среды выполнения](../Docker/alternative_runtimes_and_tools.md)
