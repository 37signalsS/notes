# Собственный mirror APT/YUM в локальной сети

Эта заметка является частью цикла статей по [управлению пакетами в Linux](../../Linux/PackageManagement/linux_package_management_overview.md).
Если вам нужно создать собственный репозиторий для распространения своих пакетов, ознакомьтесь с [созданием приватного Apt-репозитория с помощью reprepro](./deb_private_apt_repository_reprepro.md).

Когда нужен быстрый доступ к пакетам без выхода в интернет — выручит локальное зеркало. Это экономит трафик, ускоряет обновления и позволяет работать в изолированных (air-gapped) сетях.

## APT (Debian/Ubuntu)

### 1. Установка

Для создания зеркала APT нам понадобится утилита `apt-mirror` и любой HTTP-сервер для раздачи файлов по сети, например, Apache или Nginx.

```bash
sudo apt update
sudo apt install apt-mirror apache2
```

### 2. Настройка `apt-mirror`

Основной конфигурационный файл `apt-mirror` находится в `/etc/apt/mirror.list`. Он указывает, какие репозитории и архитектуры необходимо скачивать.

Откройте файл для редактирования:
```bash
sudo nano /etc/apt/mirror.list
```

Пример конфигурации для Ubuntu 20.04 (Focal Fossa):

```
############# config ##################
#
set base_path    /var/spool/apt-mirror
#
# set mirror_path  $base_path/mirror
# set skel_path    $base_path/skel
# set var_path     $base_path/var
#
set nthreads     20
set _tilde       0
#
############# end config ##############

# Пример для Ubuntu 20.04 (focal)
deb http://archive.ubuntu.com/ubuntu focal main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu focal-security main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu focal-updates main restricted universe multiverse

clean http://archive.ubuntu.com/ubuntu
```

### 3. Создание и обновление зеркала

После настройки запустите `apt-mirror`. Первый запуск может занять много времени, так как будут скачиваться все пакеты.

```bash
sudo apt-mirror
```
Зеркало будет создано в директории, указанной в `base_path` (по умолчанию `/var/spool/apt-mirror`).

### 4. Настройка веб-сервера

Чтобы клиенты могли получить доступ к зеркалу, нужно "отдать" его по HTTP. Создадим символическую ссылку из директории веб-сервера на наше зеркало.

```bash
sudo ln -s /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu /var/www/html/ubuntu
```
Теперь зеркало будет доступно по адресу `http://<ip-адрес-сервера>/ubuntu`.

### 5. Настройка клиентов

На клиентских машинах измените `/etc/apt/sources.list`, указав адрес вашего локального зеркала.

```
deb http://mirror.local/ubuntu focal main restricted universe multiverse
deb http://mirror.local/ubuntu focal-security main restricted universe multiverse
deb http://mirror.local/ubuntu focal-updates main restricted universe multiverse
```
Замените `mirror.local` на IP-адрес или DNS-имя вашего сервера-зеркала.

## YUM/DNF (RHEL/CentOS/AlmaLinux)

### 1. Установка

Для систем на базе RedHat нам понадобятся утилиты `reposync` (из пакета `yum-utils` или `dnf-utils`) и `createrepo_c` (из пакета `createrepo_c`).

```bash
sudo yum install yum-utils createrepo_c httpd
```

### 2. Синхронизация репозитория

Команда `reposync` скачивает все пакеты из указанного репозитория.

```bash
# Пример для репозитория 'base'
# --gpgcheck - проверять подписи пакетов
# -l - включить поддержку плагинов yum
# --repoid=base - идентификатор репозитория для синхронизации
# --download_path - путь для сохранения пакетов
sudo reposync --gpgcheck -l --repoid=base --download-path=/var/www/html/yum
```
Повторите команду для всех необходимых репозиториев (`updates`, `extras` и т.д.).

### 3. Создание метаданных репозитория

После скачивания пакетов необходимо создать метаданные репозитория, чтобы `yum` или `dnf` могли с ним работать.

```bash
sudo createrepo_c /var/www/html/yum/base
```
Эту команду нужно выполнять каждый раз после обновления пакетов с помощью `reposync`.

### 4. Автоматизация

Процесс синхронизации и создания метаданных можно автоматизировать с помощью `cron`, создав скрипт и добавив его в расписание (например, для запуска раз в сутки).

### 5. Настройка клиентов

На клиентских машинах в файлах `.repo` (в директории `/etc/yum.repos.d/`) измените параметр `baseurl` и отключите проверку GPG-ключей, если они не были импортированы.

Пример для `CentOS-Base.repo`:
```ini
[base]
name=CentOS-$releasever - Base - mirror.local
baseurl=http://mirror.local/yum/base/
gpgcheck=0
enabled=1
```
Замените `mirror.local` на IP-адрес или DNS-имя вашего сервера-зеркала.
