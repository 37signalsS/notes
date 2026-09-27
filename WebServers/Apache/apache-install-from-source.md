# Apache: Сборка из исходного кода, apxs, мульти-инстанс

---

## Определения

**Сборка из исходного кода** — компиляция Apache из официального tarball или git-репозитория: `./configure && make && make install`. Применяется, когда пакет дистрибутива устарел, нужны нестандартные модули/флаги или минимальный набор.

**APR (Apache Portable Runtime)** — библиотека переносимого уровня (apr, apr-util), обязательная зависимость при сборке.

**apxs (APache eXtenSion tool)** — утилита сборки/установки модулей Apache из исходников третьих сторон.

**`httpd -f <файл>`** — запуск Apache с альтернативным конфигурационным файлом (для параллельного инстанса или теста ветки конфига).

**`httpd -D <define>`** — передача условной переменной; в сочетании с `<IfDefine>` активирует фрагменты конфигурации.

**Статический vs динамический модуль** — статический вкомпилирован в бинарник (`--enable-module=static`), динамический — отдельный `.so` (`--enable-mods-shared`), загружается через `LoadModule`.

---

## Основные концепции

### Зачем собирать вручную

| Причина | Пример |
|---|---|
| Устаревшая версия в дистрибутиве | нужен свежий 2.4.x с патчами |
| Нестандартные модули | самописный/локальный модуль, специфичные флаги |
| Минимальная поверхность | отключить всё лишнее, статически нужное |
| Нетипичный путь установки | `--prefix=/opt/httpd`, несколько версий рядом |

Недостатки: ручной патчинг безопасности, отсутствие менеджера пакетов, необходимость своего systemd-юнита. Для большинства случаев предпочтителен пакет дистрибутива.

### Pipeline сборки

```
носители: apr, apr-util, pcre2, openssl-dev, expat, libxml2 (для mod_proxy_html) ...
./configure --prefix=/usr/local/httpd --enable-mods-shared=most --enable-ssl --with-mpm=event
make -j$(nproc)
make install
```

### Ключевые флаги configure

| Флаг | Назначение |
|---|---|
| `--prefix=/usr/local/httpd` | Каталог установки |
| `--with-mpm=event` | MPM по умолчанию |
| `--enable-ssl` | Включить `mod_ssl` |
| `--enable-mods-shared=most` | Модули — как `.so`, кроме всех минимальных |
| `--enable-module=static` | Конкретный модуль — статически |
| `--enable-so` | Поддержка динамической загрузки (обязательно для apxs) |
| `--with-included-apr` | Использовать bundled apr (если не ставить отдельно) |
| `--disable-cgi --disable-cgid` | Урезать ненужное |

### Мульти-инстанс через `httpd -f`

Один бинарник — несколько серверов с разными конфигами:

```ini
# /etc/httpd-alt/conf/httpd.conf (альтернативный)
ServerRoot /etc/httpd-alt
Listen 8080
PidFile /var/run/httpd-alt.pid
```

```bash
/usr/local/httpd/bin/httpd -f /etc/httpd-alt/conf/httpd.conf
```

### Условные блоки `<IfDefine>`

```apacheconf
<IfDefine DEBUG>
    LogLevel debug
</IfDefine>
```

```bash
httpd -f /etc/httpd/conf/httpd.conf -D DEBUG
```

---

## Практические сценарии

### 1. Сборка Apache 2.4 из tar-архива (RHEL-семейство)

```bash
sudo dnf groupinstall "Development Tools"
sudo dnf install apr-devel apr-util-devel pcre2-devel openssl-devel expat-devel libxml2-devel

cd /usr/local/src
curl -LO https://dlcdn.apache.org/httpd/httpd-2.4.62.tar.gz
tar xzf httpd-2.4.62.tar.gz && cd httpd-2.4.62

./configure \
  --prefix=/usr/local/httpd \
  --enable-so \
  --enable-mods-shared=most \
  --enable-ssl \
  --with-mpm=event \
  --with-included-apr
# → Configuring Apache HTTP Server... ok

make -j"$(nproc)" && sudo make install
# → make install ok

/usr/local/httpd/bin/apachectl start
curl -I http://localhost/
# → HTTP/1.1 403 Forbidden (значит сервер работает, надо настроить DocumentRoot)
```

### 2. Сборка стороннего модуля через apxs

```bash
# Пример: mod_evasive
git clone https://github.com/zdia/mod_evasive.git
cd mod_evasive
/usr/local/httpd/bin/apxs -i -a -c mod_evasive.c
# → apxs: ... linking mod_evasive.so
# → ... chmod 755 /usr/local/httpd/modules/mod_evasive.so
```

Флаги `apxs`: `-c` (компиляция), `-i` (установка), `-a` (добавить `LoadModule` в httpd.conf), `-n имя`.

### 3. Второй (тестовый) инстанс с временным конфигом

```bash
# Копия конфига с изменёнными Listen/ServerRoot
mkdir -p /tmp/httpd-test
sed 's/Listen 80/Listen 8088/' /etc/httpd/conf/httpd.conf > /tmp/httpd-test/httpd.conf

# Тест синтаксиса отдельной ветки конфига
/usr/local/httpd/bin/httpd -t -f /tmp/httpd-test/httpd.conf
# → Syntax OK

# Запуск без конфликта с основным (меняется только Listen и PidFile)
/usr/local/httpd/bin/httpd -f /tmp/httpd-test/httpd.conf -k start
ss -tlpn | grep 8088
# → LISTEN ... *:8088
```

### 4. systemd-юнит для самосборного инстанса

```ini
# /etc/systemd/system/httpd-alt.service
[Unit]
Description=Apache (custom build, alt instance)
After=network.target

[Service]
Type=forking
ExecStart=/usr/local/httpd/bin/apachectl -f /etc/httpd-alt/conf/httpd.conf -k start
ExecReload=/usr/local/httpd/bin/apachectl -f /etc/httpd-alt/conf/httpd.conf -k graceful
ExecStop=/usr/local/httpd/bin/apachectl -f /etc/httpd-alt/conf/httpd.conf -k stop
KillMode=mixed
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now httpd-alt
```

### 5. Сборка со статическим набором модулей (минимальная поверхность)

```bash
./configure --prefix=/usr/local/httpd-min \
  --enable-so \
  --enable-ssl=static \
  --enable-rewrite=static \
  --enable-mods-shared=most \
  --disable-cgi --disable-cgid --disable-dav
```

---

## Операции и команды

| Команда | Назначение | Пример вывода |
|---|---|---|
| `httpd -V` | Версия и конфигурация сборки | `Server version: Apache/2.4.62` |
| `httpd -v` | Краткая версия | `Apache/2.4.62 (Unix)` |
| `httpd -t -f CONFIG` | Проверка синтаксиса конкретного конфига | `Syntax OK` |
| `httpd -f CONFIG -k start/stop/graceful` | Управление конкретным инстансом | `httpd (pid ...) already running` |
| `apxs -i -a -c mod.c` | Собрать и установить модуль | `chmod 755 .../mod.so` |
| `httpd -M` | Загруженные модули | `ssl_module` |
| `configure --help` | Список флагов | `--enable-ssl ...` |

---

## Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
|---|---|---|
| `configure: error: APR not found` | Нет `apr-devel`/`apr-util-devel` | Установить dev-пакеты или `--with-included-apr` |
| `pcre2.h: No such file` | Нет `pcre2-devel` | `dnf install pcre2-devel` |
| `mod_ssl` собран, но не работает | Не установлен OpenSSL dev | `openssl-devel` до configure |
| `Address already in use` при старте инстанса | Конфликт `Listen` с основным | Менять порт/`ServerRoot`/`PidFile` |
| Скрипты сборки есть, сервис не поднимается при reboot | Нет systemd-юнита | Создать unit или `chkconfig` |
| SELinux блокирует самосборный httpd | Контекст/политика на `/usr/local/httpd` | `restorecon`, booleans, или переиспользовать стандартный контекст |
| `apxs: command not found` | Утилита не установлена | Использовать path `.../bin/apxs` или пакет `httpd-devel` |

---

## Лучшие практики

1. Отдавать предпочтение пакетам дистрибутива; source — только при реальной необходимости (версия, кастомные модули).
2. Всю сборку оформлять как воспроизводимый скрипт/Playbook (Ansible), фиксируя версию и флаги.
3. Для производственных инстансов создавать systemd-юнит с ограничениями (`LimitNOFILE`, `ProtectSystem`).
4. Мульти-инстанс: всегда разделять `ServerRoot`, `Listen`, `PidFile`, логи.
5. После сборки проверять `httpd -V` и `-M`; держать модули минимальным набором.
6. Патчи безопасности на самосборном Apache — на вашей ответственности; следить за CVE-рассыкой и пересобирать при необходимости.

---

## Дополнительная информация

### См. также

*   [Сборка Nginx из исходного кода](../Nginx/Core/nginx_build_from_source.md) — аналогичный pipeline для Nginx.
*   [Контейнеризация Apache](./apache-in-docker.md) — альтернатива source-сборке для воспроизводимых окружений.
*   [Обзор Apache](./apache_overview.md) — структура конфигурации и модулей по умолчанию (для сравнения с самосборной).