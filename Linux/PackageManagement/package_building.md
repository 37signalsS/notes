# Сборка пакетов

## Практические сценарии

Процесс создания собственных пакетов `.deb` или `.rpm`.

### DEB-based системы

* **Получение исходников:** `apt-get source <package_name>` (требует раскомментированных `deb-src` репозиториев в `/etc/apt/sources.list`).
* **Структура для сборки:** `debian/` директория содержит `control` (метаданные, зависимости), `rules` (сценарий сборки), `changelog` (история изменений, версия пакета).
* **Изменение версии пакета:** Утилита `dch` (`debchange`).
* **Процесс сборки:**

    ```bash
    sudo apt-get build-dep .
    cd <package_name-version>/
    dpkg-buildpackage -us -uc
    ```

### RPM-based системы

* **Получение исходников:** `dnf download --source <package_name>` (Source RPM пакеты `.src.rpm`).
* **Структура для сборки:** `~/rpmbuild` (создается `rpmdev-setuptree`) содержит `SPECS`, `SOURCES`, `BUILD`, `RPMS`, `SRPMS`.
* **Процесс сборки:**
    1. **Установка Source RPM:** `rpm -i <package_name.src.rpm>`
    2. **Установка зависимостей:** `dnf builddep ~/rpmbuild/SPECS/<package_name.spec>`
    3. **Сборка:** `rpmbuild -ba ~/rpmbuild/SPECS/<package_name.spec>` (создаст `.rpm` и `.src.rpm` в `~/rpmbuild/RPMS/` и `~/rpmbuild/SRPMS/`).

---

См. также: [Обзор управления пакетами в Linux](./linux_package_management_overview.md)
