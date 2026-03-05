# Сборка пакетов: Практические сценарии

## Сборка DEB-пакетов (Debian/Ubuntu)

### Шаг 1: Получение исходников

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

### Шаг 2: Изменение версии пакета

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

### Шаг 3: Процесс сборки

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

### Шаг 4: Проверка и установка

```bash
# Проверка собранного пакета
lintian ../package-name_version_arch.deb

# Установка собранного пакета
sudo dpkg -i ../package-name_version_arch.deb
# или
sudo apt install ./../package-name_version_arch.deb
```

## Сборка RPM-пакетов (Fedora/RHEL/CentOS)

### Шаг 1: Подготовка окружения

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

### Шаг 2: Получение исходников

```bash
# Скачать Source RPM
dnf download --source <package_name>

# Установить SRPM (распакует в ~/rpmbuild/)
rpm -i <package_name>.src.rpm

# Или вручную:
# 1. Поместить исходный.tar.gz в ~/rpmbuild/SOURCES/
# 2. Создать spec-файл в ~/rpmbuild/SPECS/
```

### Шаг 3: Установка зависимостей для сборки

```bash
# Автоматическая установка зависимостей из spec-файла
sudo dnf builddep ~/rpmbuild/SPECS/<package_name>.spec

# Ручная установка
sudo dnf install gcc make
```

### Шаг 4: Процесс сборки

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

### Шаг 5: Проверка качества

```bash
# Проверка пакета на соответствие стандартам
rpmlint ~/rpmbuild/RPMS/<arch>/<package_name>.rpm

# Проверка spec-файла
rpmlint ~/rpmbuild/SPECS/<package_name>.spec

# Установка собранного пакета
sudo dnf install ~/rpmbuild/RPMS/<arch>/<package_name>.rpm
```

---

## Связанные документы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные понятия](./basic_concepts.md)** — этапы сборки, инструменты
- **[Дополнительная информация](./additional_info.md)** — продвинутые техники, автоматизация

---

*Этот файл является частью декомпозированной документации. Исходный файл: [package_building.md](../package_building.md)*
