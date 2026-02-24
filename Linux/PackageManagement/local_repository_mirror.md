# Создание локального зеркала репозиториев APT и YUM/DNF

## Определения

**Локальное зеркало (local mirror)** — полная или частичная копия удаленного репозитория пакетов (например, Ubuntu, CentOS), размещенная в локальной сети.

## Основные понятия

Основное назначение локального зеркала:

* **Экономия трафика:** Пакеты скачиваются из интернета однократно, затем распространяются в сети.
* **Ускорение обновлений:** Установка и обновление пакетов происходят быстрее.
* **Работа в изолированных сетях:** Позволяет управлять пакетами в сетях без доступа к интернету (air-gapped environments).

## Практические сценарии

### Сценарий 1: Создание зеркала для APT (Debian/Ubuntu)

Для создания зеркала APT используются утилита `apt-mirror` и HTTP-сервер (например, Apache или Nginx).

#### Шаг 1: Установка

```bash
sudo apt update
sudo apt install apt-mirror apache2
```

#### Шаг 2: Настройка `apt-mirror`

Конфигурационный файл `/etc/apt/mirror.list` определяет скачиваемые репозитории, компоненты и архитектуры.

Пример конфигурации для Ubuntu 20.04 (Focal Fossa):

```
# /etc/apt/mirror.list

############# config ##################
# Указывает базовый путь для хранения всех файлов зеркала (пакеты, кэш и т.д.).
# По умолчанию: /var/spool/apt-mirror
set base_path    /var/spool/apt-mirror
#
# set mirror_path  $base_path/mirror # Путь к директории с непосредственно зеркалом
# set skel_path    $base_path/skel   # Путь для хранения временных файлов
# set var_path     $base_path/var     # Путь для хранения логов и других переменных данных
#
# Определяет количество потоков для одновременной загрузки пакетов.
# Увеличение значения ускоряет загрузку, но увеличивает нагрузку на сеть и сервер.
set nthreads     20
# Настройка обработки символа '~' в версиях пакетов.
# Установка в '0' позволяет избежать проблем с пакетами, содержащими этот символ.
set _tilde       0
############# end config ##############

# Определения репозиториев для зеркалирования.
# Формат: deb [опции] URI дистрибутив [компоненты]
#
# deb: Указывает на репозиторий бинарных пакетов.
# http://archive.ubuntu.com/ubuntu: Базовый URL удаленного репозитория.
# focal: Кодовое имя дистрибутива (например, Ubuntu 20.04 LTS).
# main restricted universe multiverse: Компоненты репозитория, определяющие категории программного обеспечения:
#   - main: Основные пакеты, поддерживаемые Canonical.
#   - restricted: Проприетарные драйверы.
#   - universe: Пакеты, поддерживаемые сообществом.
#   - multiverse: Пакеты, ограниченные патентами или авторским правом.
deb http://archive.ubuntu.com/ubuntu focal main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu focal-security main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu focal-updates main restricted universe multiverse

# Инструкция для apt-mirror по удалению устаревших пакетов с локального зеркала,
# которые больше не присутствуют в исходном репозитории.
clean http://archive.ubuntu.com/ubuntu
```

#### Шаг 3: Синхронизация

Запустите `apt-mirror`. Первый запуск может быть длительным.

```bash
sudo apt-mirror
```

Зеркало будет создано в директории `base_path` (по умолчанию `/var/spool/apt-mirror`).

#### Шаг 4: Публикация через веб-сервер

Для доступа клиентов сделайте зеркало доступным по HTTP. Создайте символическую ссылку из директории веб-сервера.

```bash
sudo ln -s /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu /var/www/html/ubuntu
```

Зеркало будет доступно по адресу `http://<ip-адрес-сервера>/ubuntu`.

#### Шаг 5: Настройка клиентов

На клиентских машинах отредактируйте `/etc/apt/sources.list`, указав адрес локального зеркала.

```
# /etc/apt/sources.list
deb http://mirror.local/ubuntu focal main restricted universe multiverse
deb http://mirror.local/ubuntu focal-security main restricted universe multiverse
deb http://mirror.local/ubuntu focal-updates main restricted universe multiverse
```

Замените `mirror.local` на IP-адрес или DNS-имя вашего сервера-зеркала, затем выполните `sudo apt update`.

### Сценарий 2: Создание зеркала для YUM/DNF (RHEL/CentOS/AlmaLinux)

Используются утилиты `reposync` и `createrepo_c`.

#### Шаг 1: Установка

`reposync` поставляется в пакете `yum-utils` или `dnf-utils`, `createrepo_c` — в одноименном пакете.

```bash
sudo yum install yum-utils createrepo_c httpd
```

#### Шаг 2: Синхронизация репозитория

Команда `reposync` скачивает все пакеты из указанного репозитория.

```bash
# Пример для репозитория 'base'
# --gpgcheck - проверка подписей пакетов
# -l - поддержка плагинов yum
# --repoid=base - идентификатор репозитория
# --download_path - путь сохранения пакетов
sudo reposync --gpgcheck -l --repoid=base --download-path=/var/www/html/yum
```

#### Шаг 3: Создание метаданных

После скачивания пакетов необходимо сгенерировать метаданные для работы `yum`/`dnf` с репозиторием.

```bash
sudo createrepo_c /var/www/html/yum/base
```

Эту команду следует выполнять после каждого обновления пакетов с `reposync`.

#### Шаг 4: Настройка клиентов

На клиентских машинах отредактируйте файлы в `/etc/yum.repos.d/`, изменив параметр `baseurl`.

Пример для `CentOS-Base.repo`:

```ini
[base]
name=CentOS-$releasever - Base - mirror.local
# Комментируем или удаляем строку mirrorlist
# mirrorlist=http://mirrorlist.centos.org/...
# И указываем прямой путь к нашему зеркалу
baseurl=http://mirror.local/yum/base/
gpgcheck=0
enabled=1
```

Замените `mirror.local` на IP-адрес или DNS-имя вашего сервера-зеркала, затем выполните `sudo dnf clean all`.
