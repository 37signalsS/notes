# Создание локального зеркала репозиториев APT и YUM/DNF

## Определения

**Локальное зеркало (local mirror)** — это полная или частичная копия удаленного репозитория пакетов (например, официальных репозиториев Ubuntu или CentOS), размещенная в вашей локальной сети.

Основное назначение локального зеркала — обеспечить быстрый и надежный доступ к пакетам без необходимости обращения к внешним серверам в интернете. Это решает несколько задач:
*   **Экономия трафика:** Пакеты скачиваются из интернета один раз, а затем распространяются внутри сети.
*   **Ускорение обновлений:** Установка и обновление пакетов происходит значительно быстрее.
*   **Работа в изолированных сетях:** Позволяет управлять пакетами в сетях без доступа к интернету (air-gapped environments).

## Практические сценарии

### Сценарий 1: Создание зеркала для APT (Debian/Ubuntu)

Для создания зеркала APT используется утилита `apt-mirror` и любой HTTP-сервер для раздачи файлов (например, Apache или Nginx).

#### Шаг 1: Установка
```bash
sudo apt update
sudo apt install apt-mirror apache2
```

#### Шаг 2: Настройка `apt-mirror`
Основной конфигурационный файл — `/etc/apt/mirror.list`. Он определяет, какие репозитории, их компоненты и архитектуры необходимо скачивать.

Пример конфигурации для Ubuntu 20.04 (Focal Fossa):
```
# /etc/apt/mirror.list

############# config ##################
set base_path    /var/spool/apt-mirror
#
# set mirror_path  $base_path/mirror
# set skel_path    $base_path/skel
# set var_path     $base_path/var
#
set nthreads     20
set _tilde       0
############# end config ##############

# Ubuntu 20.04 (focal)
deb http://archive.ubuntu.com/ubuntu focal main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu focal-security main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu focal-updates main restricted universe multiverse

clean http://archive.ubuntu.com/ubuntu
```

#### Шаг 3: Синхронизация
Запустите `apt-mirror`. Первый запуск может занять очень много времени, так как будут скачиваться все пакеты из указанных репозиториев.
```bash
sudo apt-mirror
```
Зеркало будет создано в директории, указанной в `base_path` (по умолчанию `/var/spool/apt-mirror`).

#### Шаг 4: Публикация через веб-сервер
Чтобы клиенты могли получить доступ к зеркалу, нужно сделать его доступным по HTTP. Самый простой способ — создать символическую ссылку из директории веб-сервера на папку с зеркалом.
```bash
sudo ln -s /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu /var/www/html/ubuntu
```
Теперь зеркало будет доступно по адресу `http://<ip-адрес-сервера>/ubuntu`.

#### Шаг 5: Настройка клиентов
На клиентских машинах необходимо отредактировать файл `/etc/apt/sources.list`, указав адрес вашего локального зеркала.
```
# /etc/apt/sources.list
deb http://mirror.local/ubuntu focal main restricted universe multiverse
deb http://mirror.local/ubuntu focal-security main restricted universe multiverse
deb http://mirror.local/ubuntu focal-updates main restricted universe multiverse
```
Замените `mirror.local` на IP-адрес или DNS-имя вашего сервера-зеркала, затем выполните `sudo apt update`.

### Сценарий 2: Создание зеркала для YUM/DNF (RHEL/CentOS/AlmaLinux)

Для систем на базе Red Hat используются утилиты `reposync` и `createrepo_c`.

#### Шаг 1: Установка
`reposync` поставляется в пакете `yum-utils` или `dnf-utils`, а `createrepo_c` — в одноименном пакете.
```bash
sudo yum install yum-utils createrepo_c httpd
```

#### Шаг 2: Синхронизация репозитория
Команда `reposync` скачивает все пакеты из указанного репозитория.
```bash
# Пример для репозитория 'base'
# --gpgcheck - проверять подписи пакетов
# -l - включить поддержку плагинов yum
# --repoid=base - идентификатор репозитория для синхронизации
# --download_path - путь для сохранения пакетов
sudo reposync --gpgcheck -l --repoid=base --download-path=/var/www/html/yum
```

#### Шаг 3: Создание метаданных
После скачивания пакетов необходимо сгенерировать метаданные, чтобы `yum` или `dnf` могли работать с репозиторием.
```bash
sudo createrepo_c /var/www/html/yum/base
```
Эту команду нужно выполнять каждый раз после обновления пакетов с помощью `reposync`.

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

