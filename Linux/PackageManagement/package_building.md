# Сборка пакетов в Linux

## Определения

**Сборка пакета (Package Building)** — процесс создания бинарного пакета (`.deb` или `.rpm`) из исходного кода программы с использованием системы сборки дистрибутива.

**Исходный пакет (Source Package)** — пакет, содержащий исходный код программы, патчи и инструкции для сборки бинарного пакета.

**Спецификация (Spec File)** — файл с расширением `.spec`, описывающий метаданные, зависимости, инструкции сборки и установки для RPM-пакета.

**Debian Directory** — директория `debian/` в исходном коде, содержащая файлы управления для сборки DEB-пакета.

## Основные понятия

### Этапы сборки

1. **Получение исходников** — загрузка исходного кода и патчей
2. **Подготовка окружения** — установка зависимостей для сборки
3. **Настройка правил сборки** — модификация `debian/rules` или `.spec` файла
4. **Сборка** — компиляция и упаковка в бинарный формат
5. **Проверка** — тестирование собранного пакета
6. **Подпись** — криптографическая подпись пакета (опционально)

### Инструменты сборки

| Система | Инструменты | Назначение |
| :--- | :--- | :--- |
| **DEB** | `dpkg-dev`, `debhelper`, `devscripts` | Базовые утилиты сборки |
| **DEB** | `pbuilder`, `sbuild`, `cowbuilder` | Чистое окружение для сборки |
| **DEB** | `debuild`, `dch`, `debchange` | Автоматизация и ведение changelog |
| **RPM** | `rpm-build`, `rpmdevtools` | Базовые утилиты сборки |
| **RPM** | `mock` | Чистое окружение для сборки (аналог pbuilder) |
| **RPM** | `rpmlint` | Проверка качества RPM-пакетов |

## Практические сценарии

### Сборка DEB-пакетов (Debian/Ubuntu)

#### Шаг 1: Получение исходников

```bash
# Включить deb-src репозитории в /etc/apt/sources.list
# deb-src http://archive.ubuntu.com/ubuntu focal main restricted universe multiverse

# Обновить кэш
sudo apt update

# Скачать исходники пакета
apt-get source <package_name>

# Скачать исходники с версией
apt-get source <package_name>=<version>

# Установить зависимости для сборки
sudo apt-get build-dep <package_name>
```

#### Шаг 2: Структура Debian-директории

```
package-name/
├── debian/
│   ├── changelog        # История изменений (версия пакета)
│   ├── control          # Метаданные и зависимости
│   ├── rules            # Сценарий сборки (Makefile-подобный)
│   ├── compat           # Версия debhelper
│   ├── copyright        # Лицензия
│   ├── docs             # Список документации
│   ├── install          # Файлы для установки
│   ├── links            # Символические ссылки
│   ├── preinst          # Скрипт перед установкой
│   ├── postinst         # Скрипт после установки
│   ├── prerm            # Скрипт перед удалением
│   ├── postrm           # Скрипт после удаления
│   ├── conffiles        # Конфигурационные файлы
│   ├── patches/         # Патчи к исходному коду (quilt)
│   └── source/
│       └── format       # Формат исходного пакета
```

#### Шаг 3: Изменение версии пакета

```bash
# Утилита dch (debchange) для редактирования changelog
cd package-name-version/
dch -i          # Увеличить версию и добавить запись
dch -e          # Редактировать последнюю запись
dch -n          # Новая версия (для Ubuntu поверх Debian)

# Формат версии в Debian/Ubuntu:
# 1.2.3-4ubuntu5
# │   │  └─ Revision для Ubuntu
# │   └───── Revision для Debian
# └───────── Версия upstream
```

#### Шаг 4: Процесс сборки

```bash
# Сборка без подписи (для локального использования)
cd package-name-version/
dpkg-buildpackage -us -uc

# Сборка с подписью
dpkg-buildpackage -S -k<GPG_KEY_ID>

# Сборка только бинарного пакета
dpkg-buildpackage -us -uc -b

# Сборка с использованием debuild (обёртка)
debuild -us -uc

# Результат:
# ../package-name_version_arch.deb    — бинарный пакет
# ../package-name_version.dsc         — описание исходников
# ../package-name_version.orig.tar.gz — исходный код
# ../package-name_version.debian.tar.xz — debian/ директория
```

#### Шаг 5: Проверка и установка

```bash
# Проверка собранного пакета
lintian ../package-name_version_arch.deb

# Установка собранного пакета
sudo dpkg -i ../package-name_version_arch.deb
# или
sudo apt install ./../package-name_version_arch.deb
```

### Сборка RPM-пакетов (Fedora/RHEL/CentOS)

#### Шаг 1: Подготовка окружения

```bash
# Установка инструментов для сборки
sudo dnf install rpm-build rpmdevtools

# Создание структуры директорий ~/rpmbuild/
rpmdev-setuptree

# Структура:
# ~/rpmbuild/
# ├── BUILD/     # Распакованные исходники
# ├── RPMS/      # Готовые бинарные пакеты
# ├── SOURCES/   # Исходные архивы и патчи
# ├── SPECS/     # Spec-файлы
# ├── SRPMS/     # Исходные RPM пакеты
# └── BUILDROOT/ # Временная корневая система
```

#### Шаг 2: Получение исходников

```bash
# Скачать Source RPM
dnf download --source <package_name>

# Установить SRPM (распакует в ~/rpmbuild/)
rpm -i <package_name>.src.rpm

# Или вручную:
# 1. Поместить исходный.tar.gz в ~/rpmbuild/SOURCES/
# 2. Создать spec-файл в ~/rpmbuild/SPECS/
```

#### Шаг 3: Структура Spec-файла

```spec
# Метаданные
Name:           mypackage
Version:        1.0.0
Release:        1%{?dist}
Summary:        Краткое описание
License:        GPL-3.0-or-later
URL:            https://example.com
Source0:        %{name}-%{version}.tar.gz

# Зависимости
BuildRequires:  gcc make
Requires:       glibc >= 2.17

# Описание
%description
Подробное описание пакета и его функциональности.

# Подготовка
%prep
%setup -q

# Сборка
%build
%configure
make %{?_smp_mflags}

# Установка
%install
make install DESTDIR=%{buildroot}

# Файлы для упаковки
%files
%{_bindir}/myapp
%{_mandir}/man1/myapp.1*

# Скрипты
%post
echo "Пост-установочный скрипт"

%preun
if [ $1 -eq 0 ]; then
    echo "Полное удаление"
fi

# Changelog
%changelog
* Wed Mar 04 2026 Your Name <you@example.com> - 1.0.0-1
- Initial package
```

#### Шаг 4: Установка зависимостей для сборки

```bash
# Автоматическая установка зависимостей из spec-файла
sudo dnf builddep ~/rpmbuild/SPECS/<package_name>.spec

# Ручная установка
sudo dnf install gcc make
```

#### Шаг 5: Процесс сборки

```bash
# Сборка бинарного и исходного пакета
rpmbuild -ba ~/rpmbuild/SPECS/<package_name>.spec

# Только бинарный пакет
rpmbuild -bb ~/rpmbuild/SPECS/<package_name>.spec

# Только исходный пакет
rpmbuild -bs ~/rpmbuild/SPECS/<package_name>.spec

# Результат в:
# ~/rpmbuild/RPMS/<arch>/package-name-version.rpm
# ~/rpmbuild/SRPMS/package-name-version.src.rpm
```

#### Шаг 6: Проверка качества

```bash
# Проверка пакета на соответствие стандартам
rpmlint ~/rpmbuild/RPMS/<arch>/<package_name>.rpm

# Проверка spec-файла
rpmlint ~/rpmbuild/SPECS/<package_name>.spec

# Установка собранного пакета
sudo dnf install ~/rpmbuild/RPMS/<arch>/<package_name>.rpm
```

## Дополнительная информация

### Продвинутые техники

#### Чистое окружение для сборки

**DEB: pbuilder**

```bash
# Установка
sudo apt-get install pbuilder debootstrap

# Создание базового окружения
sudo pbuilder create --distribution focal

# Сборка в чистом окружении
sudo pbuilder build ../package-name_version.dsc

# Результат в /var/cache/pbuilder/result/
```

**RPM: mock**

```bash
# Установка
sudo dnf install mock

# Добавление пользователя в группу mock
sudo usermod -aG mock $USER

# Сборка для Fedora 38 x86_64
mock -r fedora-38-x86_64 ~/rpmbuild/SRPMS/package-name.src.rpm

# Результат в /var/lib/mock/fedora-38-x86_64/result/
```

#### Кросс-компиляция

```bash
# DEB: Сборка для другой архитектуры
dpkg-buildpackage -aarm64 -us -uc

# RPM: Сборка для другой архитектуры
rpmbuild --target=aarch64 -ba SPECS/package.spec
```

#### Автоматизация с CI/CD

- **DEB:** Использование `git-buildpackage` для управления версиями в Git
- **RPM:** Интеграция с Copr (Fedora) или OBS (openSUSE) для автоматической сборки

### Полезные утилиты

| Утилита | Назначение |
| :--- | :--- |
| `debuild` | Обёртка для сборки DEB с проверками |
| `dch` / `debchange` | Редактирование changelog |
| `debconf` | Система конфигурации пакетов |
| `quilt` | Управление патчами в DEB |
| `rpmdev-bumpspec` | Автоматическое увеличение версии в spec |
| `fedpkg` / `centpkg` | Работа с Fedora/CentOS DistGit |

### Связанные темы

* **[Обзор управления пакетами](./linux_package_management_overview.md)** — базовые концепции
* **[Анализ и получение пакетов](./package_analysis.md)** — изучение метаданных и содержимого
* **[База данных пакетов](./package_database.md)** — расположение и структура баз данных
* **[Приватный APT-репозиторий](./deb_private_apt_repository_reprepro.md)** — публикация собственных DEB-пакетов
* **[Управление репозиториями DNF](./dnf_repository_management.md)** — публикация RPM-пакетов
