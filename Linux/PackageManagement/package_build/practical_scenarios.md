# Сборка пакетов: Практические сценарии

## Определения

Основные термины процесса сборки (исходный пакет, бинарный пакет, чистое окружение) описаны в документе **[Определения](./definitions.md)**.

## Основные концепции

Архитектура процесса сборки, структура управляющих файлов (`debian/` и `.spec`) и этапы жизненного цикла артефакта представлены в файле **[Основные понятия](./basic_concepts.md)**.

---

## Предварительные требования и настройка окружения

Перед сборкой пакетов необходимо подготовить сборочное окружение и убедиться в наличии всех инструментов.

### DEB (Debian/Ubuntu)

```bash
# Установка инструментов сборки
sudo apt update
sudo apt install -y build-essential devscripts debhelper fakeroot \
    lintian pbuilder sbuild quilt

# Валидация: проверим версии ключевых инструментов
dpkg-buildpackage --version    # → debhelper/13.x
sbuild --version               # → sbuild/0.81.x
lintian --version              # → 2.116.x

# Инициализация pbuilder (создание базового chroot)
sudo pbuilder create --debootstrapopts --variant=buildd --distribution bookworm
# → base.tgz создан в /var/cache/pbuilder/base-bookworm.tgz

# Инициализация sbuild
sudo sbuild-createchroot bookworm /srv/chroot/bookworm-amd64-sbuild http://deb.debian.org/debian
# → chroot готов к использованию
```

**Для SRE:** на сборочных нодах предварительно создайте базовые chroot для всех поддерживаемых релизов. Это сокращает время сборки на 60–80% за счет кэширования.

### RPM (RHEL/Fedora/AlmaLinux/Rocky Linux)

```bash
# Установка инструментов сборки
sudo dnf install -y rpm-build rpmdevtools rpmlint mock dnf-plugins-core

# Инициализация дерева rpmbuild
rpmdev-setuptree
# → создана структура ~/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Инициализация mock
sudo mock -r rockylinux-9-x86_64 --init
# → базовый chroot создан в /var/lib/mock/rockylinux-9-x86_64/root/
```

**Для SRE:** используйте `mock` для всех production-сборок. Прямой `rpmbuild` на хосте допустим только для отладки, так как он оставляет artefact-зависимости в системе.

---

## Практические сценарии

### Сценарий 1: Сборка DEB-пакетов (Debian/Ubuntu)

#### Вариант А: Модификация существующего пакета (Workflow с Quilt)

**Применение:** наложение патчей или изменение параметров компиляции официальных пакетов.

**Теория:** Система quilt управляет серией патчей поверх апстрим-кода. Патчи хранятся в `debian/patches/` и применяются последовательно. Это позволяет легко обновлять апстрим-версию: достаточно заменить `orig.tar.gz` и пересобрать серию.

1.  **Получение исходников:**
    ```bash
    # Включите deb-src в /etc/apt/sources.list если отключено
    sudo apt update && apt-get source <package_name>
    sudo apt-get build-dep <package_name>
    cd <package_dir>/
    ```

2.  **Управление патчами:**
    ```bash
    export QUILT_PATCHES=debian/patches
    quilt push -a             # Применить все текущие патчи
    quilt new security_fix.patch
    quilt add src/main.c      # Регистрируем файл в quilt ДО правок
    # ... правка src/main.c ...
    quilt refresh             # Сохранение изменений в файл патча
    quilt pop -a              # Откат для чистой сборки (dpkg-buildpackage применит сам)
    ```

3.  **Версионирование:**
    ```bash
    # dch (debchange) добавит запись и увеличит ревизию
    dch -i "Applied security patch for CVE-XXXX"
    ```

4.  **Сборка:**
    ```bash
    # -us -uc: без GPG подписи (для тестов)
    # -b: только бинарный пакет
    dpkg-buildpackage -us -uc -b
    ```

5.  **Валидация:**
    ```bash
    # Проверка lintian (политика Debian)
    lintian ../package_1.0-1_amd64.deb
    # → E/W сообщения; ошибки E блокируют попадание в репозиторий

    # Проверка контрольных сумм
    debsums -s ../package_1.0-1_amd64.deb

    # Просмотр состава
    dpkg-deb --contents ../package_1.0-1_amd64.deb
    ```

6.  **Очистка:**
    ```bash
    # Возврат к чистому состоянию
    quilt pop -a
    git checkout debian/patches/
    ```

**Типичные ошибки:**
- `quilt push: patch does not apply` — апстрим-версия изменилась, патч устарел. Решение: `quilt refresh --refresh` или откат.
- `dpkg-buildpackage: error: cannot access archive` — отсутствует `orig.tar.gz`. Решение: `get-orig-source` в `debian/rules` или ручная загрузка.

#### Вариант Б: Создание метапакета (Dependency Package)

Метапакеты используются SRE для управления списком обязательного ПО на всех серверах через одну зависимость.

1.  **Установка инструментов**: `sudo apt install equivs`.
2.  **Создание шаблона**: `equivs-control my-corporate-env.control`.
3.  **Настройка**: Отредактируйте файл, указав `Package: my-corporate-env` и `Depends: htop, vim, curl, nginx`.
4.  **Сборка**: `equivs-build my-corporate-env.control`.
5.  **Валидация:**
    ```bash
    # Проверка содержимого
    dpkg-deb --info my-corporate-env_1.0_all.deb
    # → Package: my-corporate-env, Depends: htop, vim, curl, nginx

    # Установка и проверка разрешения зависимостей
    sudo dpkg -i my-corporate-env_1.0_all.deb
    apt-cache depends my-corporate-env
    ```

#### Вариант В: Сборка из upstream-архива (без deb-src)

**Применение:** сборка пакета для стороннего ПО, для которого нет исходников в репозитории.

1.  **Загрузка исходников:**
    ```bash
    wget https://example.com/package-1.0.tar.gz
    tar xzf package-1.0.tar.gz
    cd package-1.0/
    ```

2.  **Создание структуры debian/:**
    ```bash
    # dh_make создаст шаблонную структуру
    dh_make -s -y -f ../package-1.0.tar.gz
    # → -s: single binary (один бинарный пакет)
    # → -y: отвечать "yes" на все вопросы
    ```

3.  **Настройка управляющих файлов:**
    ```bash
    # Отредактируйте ключевые файлы:
    # debian/control: Package, Depends, Description
    # debian/rules: %: override_dh_auto_configure / make
    # debian/changelog: dch -i "Initial release"
    ```

4.  **Сборка:**
    ```bash
    debuild -us -uc -b
    # или
    dpkg-buildpackage -us -uc -b
    ```

5.  **Валидация:**
    ```bash
    lintian ../package_1.0-1_amd64.deb
    # Исправьте все E: ошибки перед распространением
    ```

#### Вариант Г: Сборка в изолированном окружении sbuild

**Применение:** гарантированная воспроизводимость и отсутствие влияния хостовой среды.

```bash
# 1. Подготовка источника (только .dsc + архивы)
# Предполагается, что package_1.0-1.dsc и архивы уже готовы

# 2. Сборка
sbuild -d bookworm --no-clean package_1.0-1.dsc

# Параметры:
#   -d bookworm          → целевой дистрибутив
#   --no-clean           → сохранить chroot для отладки (в production используйте --clean)
#   --arch=arm64         → кросс-архитектурная сборка (требует qemu-user-static)

# 3. Проверка результатов
ls ../*.deb
lintian --fail-on-error ../package_1.0-1_amd64.changes

# 4. Очистка chroot после отладки
sbuild --clean
```

**Валидация:**
```bash
# Проверка, что пакет установляется в чистой среде
sudo sbuild-chroot bookworm-amd64-sbuild
# → внутри chroot:
dpkg -i /build/package_1.0-1_amd64.deb
```

---

### Сценарий 2: Сборка RPM-пакетов (Fedora/RHEL/CentOS)

#### Вариант А: Пересборка из SRPM

**Применение:** обновление параметров сборки для корпоративного стандарта.

1.  **Инициализация дерева**: `rpmdev-setuptree`.
2.  **Получение и распаковка:**
    ```bash
    dnf download --source <package_name>
    rpm -i <package_name>.src.rpm
    # → файлы распакованы в ~/rpmbuild/SPECS/ и SOURCES/
    ```
3.  **Установка build-зависимостей:**
    ```bash
    sudo dnf builddep ~/rpmbuild/SPECS/<package_name>.spec
    # → автоматически установлены все BuildRequires
    ```
4.  **Применение патчей (при необходимости):**
    ```bash
    # Скопируйте патч в SOURCES/
    cp fix.patch ~/rpmbuild/SOURCES/
    # Добавьте в .spec:
    # Patch0: fix.patch
    # В секции %prep добавьте:
    # %patch0 -p1
    ```
5.  **Сборка:**
    ```bash
    rpmbuild -ba ~/rpmbuild/SPECS/<package_name>.spec
    ```

6.  **Валидация:**
    ```bash
    # Проверка rpmlint
    rpmlint ~/rpmbuild/SPECS/<package_name>.spec
    rpmlint ~/rpmbuild/RPMS/x86_64/package-1.0-1.el9.x86_64.rpm

    # Просмотр метаданных
    rpm -qip ~/rpmbuild/RPMS/x86_64/package-1.0-1.el9.x86_64.rpm

    # Проверка GPG подписи (если подписана)
    rpm -K ~/rpmbuild/RPMS/x86_64/package-1.0-1.el9.x86_64.rpm
    # → digests signatures OK
    ```

#### Вариант Б: Создание пакета для собственного ПО (SPEC-workflow)

1.  **Создание скелета**: `rpmdev-newspec ~/rpmbuild/SPECS/myapp.spec`.
2.  **Заполнение ключевых секций:**
    *   `Name:`, `Version:`, `Release:`, `Summary:`
    *   `Source0:` — ссылка на архив в `~/rpmbuild/SOURCES/` или URL
    *   `License:`, `URL:`
    *   `BuildRequires:` — зависимости сборки
    *   `Requires:` — runtime-зависимости
3.  **Секции сборки:**
    *   `%prep`: `%setup -q` (распаковка) + `%patch0` (если есть патчи)
    *   `%build`: `./configure && make %{?_smp_mflags}`
    *   `%install`: `make install DESTDIR=%{buildroot}`
    *   `%files`: перечисление файлов (`%{_bindir}/myapp`, `%doc README.md`)
4.  **Линтинг и сборка:**
    ```bash
    rpmlint ~/rpmbuild/SPECS/myapp.spec
    rpmbuild -bb ~/rpmbuild/SPECS/myapp.spec
    ```

5.  **Валидация:**
    ```bash
    # Проверка содержимого
    rpm -qpl ~/rpmbuild/RPMS/x86_64/myapp-1.0-1.el9.x86_64.rpm

    # Проверка контрольных сумм
    rpmlint ~/rpmbuild/RPMS/x86_64/myapp-1.0-1.el9.x86_64.rpm

    # Тестовая установка
    sudo rpm -ivh ~/rpmbuild/RPMS/x86_64/myapp-1.0-1.el9.x86_64.rpm
    myapp --version
    ```

#### Вариант В: Сборка в изолированном окружении mock

**Применение:** гарантированная воспроизводимость и безопасность.

```bash
# 1. Инициализация mock (если еще не сделано)
sudo mock -r rockylinux-9-x86_64 --init

# 2. Сборка SRPM (если есть spec и sources)
mock -r rockylinux-9-x86_64 --buildsrpm \
    --spec ~/rpmbuild/SPECS/myapp.spec \
    --sources ~/rpmbuild/SOURCES/

# 3. Сборка бинарного RPM из SRPM
mock -r rockylinux-9-x86_64 --rebuild \
    ~/rpmbuild/SRPMS/myapp-1.0-1.el9.src.rpm

# 4. Извлечение результатов
cp /var/lib/mock/rockylinux-9-x86_64/result/*.rpm ~/rpmbuild/RPMS/x86_64/

# 5. Очистка окружения
mock -r rockylinux-9-x86_64 --clean
```

**Валидация:**
```bash
# Проверка в изолированной среде
mock -r rockylinux-9-x86_64 --shell --no-clean
# → внутри chroot:
rpm -Uvh /builddir/build/BUILDROOT/myapp-1.0-1.el9.x86_64/myapp
```

---

### Сценарий 3: Бэкпортирование пакетов

**Применение:** перенос новой версии ПО в старый релиз дистрибутива (например, bullseye-backports или EPEL).

#### DEB: Backport в стабильный релиз

1.  **Получение исходников:**
    ```bash
    # Из целевого дистрибутива (например, bookworm-backports)
    apt-get source -t bookworm-backports package-name
    # Или вручную: wget + tar
    ```

2.  **Обновление версии:**
    ```bash
    cd package-name-*/
    dch --local ~bookworm1 "Backport to bookworm"
    # → debian/changelog: 1.0-1~bookworm1
    ```

3.  **Адаптация патчей:**
    ```bash
    # Проверка применения патчей
    quilt push -a
    # Если патчи не применяются — обновите их
    quilt refresh --refresh
    ```

4.  **Сборка и тестирование:**
    ```bash
    sudo apt-get build-dep -t bookworm .
    dpkg-buildpackage -us -uc -b
    lintian ../package-name_1.0-1~bookworm1_amd64.deb
    ```

5.  **Распространение:**
    ```bash
    # Для локального репозитория
    reprepro -b /srv/repo includedeb bookworm-backports ../package-name_1.0-1~bookworm1_amd64.deb
    ```

#### RPM: Backport в старый релиз

1.  **Обновление релиз-тега:**
    ```bash
    rpmdev-bumpspec -c "Backport to EL9" ~/rpmbuild/SPECS/package.spec
    # → Release: 1.el9_backport
    ```

2.  **Адаптация:**
    ```bash
    # Проверка BuildRequires на наличие в целевом релизе
    mock -r rockylinux-9-x86_64 --shell --no-clean -c "dnf repoquery --whatprovides <require>"
    ```

3.  **Сборка:**
    ```bash
    mock -r rockylinux-9-x86_64 --rebuild package-1.0-1.el9.src.rpm
    ```

---

### Сценарий 4: Диагностика и устранение ошибок сборки

| Симптом / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Missing Build-Depends** | Не установлен заголовочный файл или утилита. | DEB: `apt-get build-dep <pkg>`; RPM: `dnf builddep <.spec>`. |
| **Installed but unpackaged files** | Файл создан в BuildRoot, но не указан в `%files`. | Добавьте путь в секцию `%files` (RPM) или `debian/<pkg>.install` (DEB). |
| **Symbol lookup error** | Несоответствие версий разделяемых библиотек. | Проверьте runtime-зависимости и используйте чистое окружение. |
| **Permission denied in BuildRoot** | Попытка записи вне фиктивного корня. | Проверьте `DESTDIR` (DEB) или `%{buildroot}` (RPM). |
| **File not found: /bin/sh** | В chroot отсутствует `/bin/sh` или `.` не монтируется. | Проверьте наличие `bash`/`dash` и смонтированных `/proc`, `/sys`, `/dev`. |
| **No matching manifest** | Встроенный макро `%{_arch}` не совпадает с целевой архитектурой. | Проверьте `--target` или `--arch` параметры сборки. |
| `quilt push: patch does not apply` | Апстрим-версия изменилась, патч устарел. | Пересоздайте патч через `quilt refresh --refresh` или откатите его. |
| `lintian: unstripped-binary-or-object` | В пакет попали бинарники с отладочными символами. | Добавьте `dh_strip --debug-dbgsym` в `debian/rules`. |
| `rpmlint: uncompressed-manpage` | Man-страницы не сжаты gzip. | Добавьте `%global _mandir /usr/share/man` и убедитесь, что `%doc` включает MANPATH. |
| `dpkg-shlibdeps: cannot find library` | У пакета нет явной зависимости на shared-объект. | Добавьте `${shlibs:Depends}` в поле `Depends` в `debian/control`. |

---

### Интеграция с конфигурационным управлением

В корпоративных средах сборка пакетов часто интегрируется с Ansible для автоматизации подготовки сборочных окружений:

```yaml
- name: Установка инструментов сборки DEB
  apt:
    name:
      - build-essential
      - devscripts
      - debhelper
      - fakeroot
      - sbuild
    state: present
  when: ansible_facts['os_family'] == 'Debian'

- name: Создание chroot окружения для сборки
  command: >
    sbuild-createchroot bookworm /srv/chroot/bookworm-amd64-sbuild
    http://deb.debian.org/debian
  args:
    creates: /srv/chroot/bookworm-amd64-sbuild
  become: true
```

---

## Дополнительная информация

Продвинутые техники (изолированная сборка в `mock`/`sbuild`, кросс-компиляция и воспроизводимость) описаны в документе **[Дополнительная информация](./additional_info.md)**.

### Связанные документы

- **[Определения](./definitions.md)** — глоссарий и типы зависимостей.
- **[Основные понятия](./basic_concepts.md)** — этапы сборки, архитектура DEB и RPM.
- **[Анализ и распаковка пакетов](../package_analysis.md)** — инструменты `dpkg-deb`, `rpm2cpio`.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами при установке бэкпортов.
- **[Chroot](../../Core/chroot.md)** — механизм изоляции, используемый `mock`, `sbuild` и `pbuilder`.
- **[Управление репозиториями DEB](../deb_repositories_sources_list.md)** — настройка источников ПО.
- **[База данных пакетов](../package_database.md)** — как установленные пакеты регистрируются в системе.
