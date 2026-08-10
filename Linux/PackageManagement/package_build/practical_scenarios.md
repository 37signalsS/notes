# Сборка пакетов: Практические сценарии

## Определения

Основные термины процесса сборки (исходный пакет, бинарный пакет, чистое окружение) описаны в документе **[Определения](./definitions.md)**.

## Основные концепции

Архитектура процесса сборки, структура управляющих файлов (`debian/` и `.spec`) и этапы жизненного цикла артефакта представлены в файле **[Основные понятия](./basic_concepts.md)**.

---

## Практические сценарии

### Сценарий 1: Сборка DEB-пакетов (Debian/Ubuntu)

#### Вариант А: Модификация существующего пакета (Workflow с Quilt)

Применяется для наложения патчей или изменения параметров компиляции официальных пакетов.

1.  **Подготовка**:
    ```bash
    # Убедитесь, что deb-src активны в sources.list
    sudo apt update && apt-get source <package_name>
    sudo apt-get build-dep <package_name>
    cd <package_dir>/
    ```

2.  **Управление патчами**:
    ```bash
    export QUILT_PATCHES=debian/patches
    quilt push -a             # Применить все текущие патчи
    quilt new security_fix.patch
    quilt add src/main.c      # Регистрируем файл в quilt ДО правок
    # ... правка src/main.c ...
    quilt refresh             # Сохранение изменений в файл патча
    quilt pop -a              # Откат для чистой сборки (dpkg-buildpackage применит сам)
    ```

3.  **Версионирование**:
    ```bash
    # dch (debchange) добавит запись и увеличит ревизию
    dch -i "Applied security patch for CVE-XXXX"
    ```

4.  **Сборка**:
    ```bash
    # -us -uc: без GPG подписи (для тестов)
    # -b: только бинарный пакет
    dpkg-buildpackage -us -uc -b
    ```

#### Вариант Б: Создание метапакета (Dependency Package)

Метапакеты используются SRE для управления списком обязательного ПО на всех серверах через одну зависимость.

1.  **Установка инструментов**: `sudo apt install equivs`.
2.  **Создание шаблона**: `equivs-control my-corporate-env.control`.
3.  **Настройка**: Отредактируйте файл, указав `Package: my-corporate-env` и `Depends: htop, vim, curl, nginx`.
4.  **Сборка**: `equivs-build my-corporate-env.control`.

---

### Сценарий 2: Сборка RPM-пакетов (Fedora/RHEL/CentOS)

#### Вариант А: Пересборка из SRPM

Стандартный метод обновления параметров сборки для корпоративного стандарта.

1.  **Инициализация дерева**: `rpmdev-setuptree`.
2.  **Получение**: `dnf download --source <package_name> && rpm -i <package_name>.src.rpm`.
3.  **Сборка**:
    ```bash
    # Установка зависимостей сборки
    sudo dnf builddep ~/rpmbuild/SPECS/<package_name>.spec
    # Сборка бинарного и исходного пакетов
    rpmbuild -ba ~/rpmbuild/SPECS/<package_name>.spec
    ```

#### Вариант Б: Создание пакета для собственного ПО (SPEC-workflow)

1.  **Создание скелета**: `rpmdev-newspec ~/rpmbuild/SPECS/myapp.spec`.
2.  **Заполнение ключевых секций**:
    *   `Source0`: Ссылка на архив в `~/rpmbuild/SOURCES/`.
    *   `%prep`: `%setup -q` (распаковка).
    *   `%build`: `./configure && make %{?_smp_mflags}`.
    *   `%install`: `make install DESTDIR=%{buildroot}`.
    *   `%files`: Перечисление файлов (например, `%{_bindir}/myapp`).
3.  **Линтинг и сборка**:
    ```bash
    rpmlint ~/rpmbuild/SPECS/myapp.spec
    rpmbuild -bb ~/rpmbuild/SPECS/myapp.spec
    ```

---

### Сценарий 3: Диагностика и устранение ошибок сборки

| Симптом / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Missing Build-Depends** | Не установлен заголовочный файл или утилита. | Проверьте `Build-Depends` (DEB) или `BuildRequires` (RPM). |
| **Installed but unpackaged files** | Файл создан в BuildRoot, но не указан в `%files`. | Добавьте путь в секцию `%files` (только для RPM). |
| **Symbol lookup error** | Несоответствие версий разделяемых библиотек. | Проверьте зависимости `Runtime` и убедитесь в использовании чистой среды. |
| **Permission denied in BuildRoot** | Попытка записи вне фиктивного корня. | Проверьте параметры `DESTDIR` или макрос `%{buildroot}`. |

---

## Дополнительная информация

Продвинутые техники (изолированная сборка в `mock`/`sbuild`, кросс-компиляция и воспроизводимость) описаны в документе **[Дополнительная информация](./additional_info.md)**.

### Связанные документы

- **[Определения](./definitions.md)** — глоссарий и типы зависимостей.
- **[Основные понятия](./basic_concepts.md)** — этапы жизненного цикла сборки.
- **[Анализ и распаковка пакетов](../package_analysis.md)** — инструменты `dpkg-deb`, `rpm2cpio`.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами при установке бэкпортов.
