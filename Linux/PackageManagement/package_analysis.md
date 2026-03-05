# Анализ и получение пакетов в Linux

## Определения

**Анализ пакета** — процесс изучения метаданных, содержимого, зависимостей и скриптов пакета без его установки.

**Метаданные пакета** — информация о пакете: версия, зависимости, описание, maintainer, размер, архитектура.

**Содержимое пакета** — список файлов, которые будут установлены при установке пакета.

## Основные понятия

### Структура пакетов

#### DEB-пакет (`.deb`)

Архив формата `ar`, содержащий три компонента:

- `debian-binary` — версия формата пакета
- `control.tar.gz` — метаданные и скрипты (control, md5sums, preinst, postinst, prerm, postrm)
- `data.tar.gz` — файлы для установки в систему

#### RPM-пакет (`.rpm`)

Состоит из:

- Заголовок (header) — метаданные в бинарном формате
- Подпись (signature) — GPG-подпись для проверки подлинности
- Тело (payload) — cpio-архив с файлами пакета

### Скрипты пакетов (scriptlets)

| Скрипт | Выполняется | Назначение |
| :--- | :--- | :--- |
| `preinst` / `%pre` | Перед установкой | Проверка условий, резервное копирование |
| `postinst` / `%post` | После установки | Регистрация сервисов, настройка |
| `prerm` / `%preun` | Перед удалением | Остановка сервисов, сохранение данных |
| `postrm` / `%postun` | После удаления | Очистка конфигураций, уведомление |

## Практические сценарии

### Получение файлов пакетов без установки

#### DEB-based системы (Debian, Ubuntu)

```bash
# Скачать пакет без установки
apt-get download <package_name>

# Скачать пакет со всеми зависимостями (в кэш /var/cache/apt/archives/)
apt-get install --download-only <package_name>

# Поиск пакета по содержимому файла (утилита apt-file)
sudo apt-get update && sudo apt-get install apt-file && apt-file update
apt-file search <file_path_or_name>

# Поиск пакета, которому принадлежит установленный файл
dpkg -S <file_path>

# Поиск пакета по предоставленной команде
apt-file search bin/<command_name>
```

#### RPM-based системы (Fedora, RHEL, CentOS)

```bash
# Скачать пакет без установки
dnf download <package_name>

# Скачать пакет со всеми зависимостями
dnf install --downloadonly <package_name>

# Поиск пакета, которому принадлежит файл (до или после установки)
dnf provides '*/<file_name>'
dnf provides <command_name>

# Поиск пакета по установленному файлу
rpm -qf <file_path>
```

### Анализ метаданных и содержимого

#### DEB-based системы

```bash
# Метаданные из файла .deb пакета
dpkg --info <package_name.deb>
# или
dpkg-deb --info <package_name.deb>

# Содержимое файла .deb пакета (список файлов)
dpkg --contents <package_name.deb>
# или
dpkg-deb --contents <package_name.deb>

# Метаданные установленного пакета
dpkg -s <package_name>

# Статус и подробная информация
dpkg-query -W -f='${Package}: ${Version}\n' <package_name>

# Список файлов установленного пакета
dpkg -L <package_name>

# Конфигурационные файлы пакета
dpkg -L <package_name> | grep /etc/

# Зависимости установленного пакета
dpkg -s <package_name> | grep Depends

# Версия установленного пакета
dpkg -l <package_name>
```

#### RPM-based системы

```bash
# Метаданные из файла .rpm пакета
rpm -qip <package_name.rpm>

# Содержимое файла .rpm пакета (список файлов)
rpm -qlp <package_name.rpm>

# Метаданные установленного пакета
rpm -qi <package_name>

# Список файлов установленного пакета
rpm -ql <package_name>

# Показать скрипты внутри пакета
rpm -qp --scripts <package_name.rpm>

# Показать все установленные пакеты
rpm -qa

# Фильтрованный список установленных пакетов
rpm -qa | grep <pattern>

# Информация о зависимостях пакета
rpm -qR <package_name>
# или
dnf deplist <package_name>

# Конфигурационные файлы пакета
rpm -qc <package_name>

# Документация пакета
rpm -qd <package_name>
```

### Извлечение содержимого пакетов (распаковка)

#### DEB-based системы

```bash
# Распаковать .deb пакет с помощью dpkg-deb
dpkg-deb --extract <package_name.deb> <output_dir>

# Распаковать с разделением на control и data
dpkg-deb --control <package_name.deb> <control_output_dir>
dpkg-deb --extract <package_name.deb> <data_output_dir>

# Ручная распаковка через ar (показывает внутреннюю структуру)
ar x <package_name.deb>
# Создаст: debian-binary, control.tar.gz, data.tar.gz
```

#### RPM-based системы

```bash
# Конвертация RPM в cpio и распаковка
rpm2cpio <package_name.rpm> | cpio -idmv

# Опции cpio:
# -i: extract (извлечение)
# -d: create directories (создать директории)
# -m: preserve modification time (сохранить время модификации)
# -v: verbose (подробный вывод)
```

### Поиск пакетов в веб-интерфейсе

| Дистрибутив | URL |
| :--- | :--- |
| **Debian** | [packages.debian.org](https://packages.debian.org/) |
| **Ubuntu** | [packages.ubuntu.com](https://packages.ubuntu.com/) |
| **Fedora** | [packages.fedoraproject.org](https://packages.fedoraproject.org/) |
| **RHEL/CentOS** | [pkgs.org](https://pkgs.org/) |

---

## Дополнительная информация

### Низкоуровневые утилиты: dpkg и rpm

Утилиты `dpkg` и `rpm` не разрешают зависимости автоматически. Используются для:

- Ручной установки локальных пакетов
- Удаления проблемных пакетов
- Запроса информации о пакетах
- Восстановления системы при повреждении базы данных

#### DEB-based системы (`dpkg`)

```bash
# Установка пакета из .deb файла
sudo dpkg -i <package_name.deb>

# Разрешение зависимостей после неудачной установки
sudo apt-get install -f

# Удаление пакета (сохранение конфигурационных файлов)
sudo dpkg -r <package_name>

# Полное удаление пакета (с конфигурационными файлами)
sudo dpkg -P <package_name>

# Переконфигурация установленного пакета
sudo dpkg-reconfigure <package_name>

# Проверка целостности установленных файлов
debsums <package_name>
```

#### RPM-based системы (`rpm`)

```bash
# Установка пакета из .rpm файла
sudo rpm -i <package_name.rpm>

# Обновление пакета
sudo rpm -U <package_name.rpm>

# Понижение версии пакета
sudo rpm -F <package_name.rpm>

# Удаление пакета
sudo rpm -e <package_name>

# Принудительная установка (игнорирование ошибок)
sudo rpm -i --force <package_name.rpm>

# Проверка целостности установленного пакета
rpm -V <package_name>
```

### Сравнение высокоуровневых и низкоуровневых операций

| Операция | DEB (высокий уровень) | DEB (низкий уровень) | RPM (высокий уровень) | RPM (низкий уровень) |
| :--- | :--- | :--- | :--- | :--- |
| **Установка из файла** | `apt install ./pkg.deb` | `dpkg -i pkg.deb` | `dnf install ./pkg.rpm` | `rpm -i pkg.rpm` |
| **Разрешение зависимостей** | Автоматически | `apt-get install -f` | Автоматически | Вручную |
| **Удаление** | `apt remove pkg` | `dpkg -r pkg` | `dnf remove pkg` | `rpm -e pkg` |
| **Обновление базы** | Автоматически | — | Автоматически | `rpm --rebuilddb` |

### Связанные темы

- **[Обзор управления пакетами](./linux_package_management_overview.md)** — базовые концепции
- **[База данных пакетов](./package_database.md)** — расположение и структура баз данных
- **[Сборка пакетов](./package_building.md)** — создание собственных пакетов
- **[Управление репозиториями DEB](./deb_repositories_sources_list.md)** — настройка источников пакетов
- **[Управление репозиториями DNF](./dnf_repository_management.md)** — настройка репозиториев для RPM
