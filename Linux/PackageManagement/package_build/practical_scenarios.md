# Сборка пакетов: Практические сценарии

## Определения

Основные термины (исходный пакет, бинарный пакет, чистое окружение) описаны в документе **[Определения](./definitions.md)**.

## Основные концепции

Этапы сборки, инструментарий и архитектура управляющих файлов представлены в файле **[Основные понятия](./basic_concepts.md)**.

---

## Практические сценарии

### Сценарий 1: Сборка DEB-пакетов (Debian/Ubuntu)

#### Шаг 1: Получение исходного кода и зависимостей

```bash
# Включите репозитории исходного кода (deb-src) в /etc/apt/sources.list
# Пример: deb-src http://archive.ubuntu.com/ubuntu focal main universe

# Обновите индекс пакетов
sudo apt update

# Загрузите исходный код пакета
apt-get source <package_name>

# Установите все необходимые зависимости для сборки (Build-Depends)
sudo apt-get build-dep <package_name>
```

#### Шаг 2: Изменение версии и журнала изменений

```bash
# Перейдите в директорию с исходниками
cd package-name-version/

# Используйте dch (debchange) для добавления записи в changelog
dch -i          # Увеличить версию и открыть редактор
dch -n          # Добавить новую версию для Ubuntu поверх Debian

# Формат версии в DEB (Debian Package):
# 1.2.3-4ubuntu5
# │   │  └─ Ревизия для Ubuntu (Revision)
# │   └───── Ревизия для Debian (Revision)
# └───────── Версия апстрима (Upstream)
```

#### Шаг 3: Процесс сборки

```bash
# Сборка бинарного пакета без цифровой подписи
dpkg-buildpackage -us -uc -b

# Сборка полного комплекта (исходники + бинарники) с использованием debuild
debuild -us -uc

# Результаты сборки появятся на уровень выше:
# ../package-name_version_arch.deb    — бинарный пакет для установки
# ../package-name_version.dsc         — описание исходного пакета
# ../package-name_version.orig.tar.gz — оригинальный архив исходного кода
```

#### Шаг 4: Проверка и установка

```bash
# Проверьте пакет на соответствие стандартам Debian
lintian ../package-name_version_arch.deb

# Установите пакет локально
sudo apt install ./../package-name_version_arch.deb
```

---

### Сценарий 2: Сборка RPM-пакетов (Fedora/RHEL/CentOS)

#### Шаг 1: Подготовка рабочего дерева

`RPM` (Red Hat Package Manager) требует специфической структуры директорий для сборки.

```bash
# Установка базового инструментария
sudo dnf install rpm-build rpmdevtools

# Создание структуры директорий ~/rpmbuild/
rpmdev-setuptree

# Назначение папок:
# ~/rpmbuild/SOURCES/   — исходные архивы (.tar.gz) и патчи
# ~/rpmbuild/SPECS/     — конфигурационные .spec файлы
# ~/rpmbuild/RPMS/      — готовые бинарные пакеты
# ~/rpmbuild/SRPMS/     — исходные пакеты (.src.rpm)
```

#### Шаг 2: Получение и распаковка SRPM (Source RPM)

```bash
# Скачивание исходного пакета
dnf download --source <package_name>

# Установка SRPM (распаковка архивов и spec-файла в дерево rpmbuild)
rpm -i <package_name>.src.rpm
```

#### Шаг 3: Установка зависимостей сборки

```bash
# Автоматическая установка зависимостей, указанных в BuildRequires
sudo dnf builddep ~/rpmbuild/SPECS/<package_name>.spec
```

#### Шаг 4: Сборка пакета

```bash
# Сборка бинарного и исходного пакетов
rpmbuild -ba ~/rpmbuild/SPECS/<package_name>.spec

# Сборка только бинарного пакета (.rpm)
rpmbuild -bb ~/rpmbuild/SPECS/<package_name>.spec
```

#### Шаг 5: Проверка и установка

```bash
# Проверка качества собранного пакета
rpmlint ~/rpmbuild/RPMS/<arch>/<package_name>.rpm

# Установка пакета в систему
sudo dnf install ~/rpmbuild/RPMS/<arch>/<package_name>.rpm
```

---

## Дополнительная информация

Продвинутые техники (изолированное окружение `mock`/`pbuilder`, кросс-компиляция, автоматизация) описаны в документе **[Дополнительная информация](./additional_info.md)**.

### Связанные документы

- **[Определения](./definitions.md)** — глоссарий терминов сборки.
- **[Основные понятия](./basic_concepts.md)** — этапы сборки и структура файлов.
- **[Обзор управления пакетами](../linux_package_management_overview.md)** — сравнение систем DEB и RPM.
