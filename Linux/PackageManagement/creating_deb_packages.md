# Создание простого .deb пакета с помощью dpkg-dev

Это руководство описывает процесс создания простого пакета Debian (`.deb`) с использованием утилиты `dpkg-dev`. Этот метод подходит для быстрой упаковки скриптов или небольших приложений для внутреннего использования.

## 1. Установка необходимых инструментов

Для создания пакетов нам потребуется `dpkg-dev`:

```bash
sudo apt-get update
sudo apt-get install dpkg-dev
```

## 2. Структура директорий пакета

Пакет Debian имеет определенную структуру директорий. Основные компоненты:
*   Корневая директория пакета (например, `my-package-1.0`).
*   Директория `DEBIAN/` внутри корневой директории, содержащая метаданные и скрипты управления пакетом.
*   Директории, имитирующие файловую систему целевой системы (например, `usr/bin/`, `etc/`).

Пример структуры:

```
my-package-1.0/
├── DEBIAN/
│   └── control
├── usr/
│   └── bin/
│       └── my-script
└── etc/
    └── my-package/
        └── config.conf
```

## 3. Создание файла `control`

Файл `DEBIAN/control` содержит метаданные пакета, такие как имя, версия, описание, зависимости и т.д.

Создайте директорию для вашего пакета и файл `DEBIAN/control`:

```bash
mkdir -p my-package-1.0/DEBIAN
nano my-package-1.0/DEBIAN/control
```

Пример содержимого файла `control`:

```
Package: my-package
Version: 1.0
Section: misc
Priority: optional
Architecture: amd64
Maintainer: Rebrain <campaign@rebrain.com>
Description: A simple example Debian package
```

*   `Package`: Имя пакета.
*   `Version`: Версия пакета.
*   `Section`: Категория пакета (например, `utils`, `net`, `misc`).
*   `Priority`: Приоритет пакета (например, `optional`, `standard`).
*   `Architecture`: Архитектура, для которой предназначен пакет (например, `amd64`, `all`).
*   `Maintainer`: Имя и email сопровождающего пакета.
*   `Description`: Краткое описание пакета.

## 4. Добавление файлов в пакет

Разместите файлы, которые должны быть включены в пакет, в соответствующих директориях внутри корневой директории пакета, имитируя их расположение в целевой системе.

Например, создадим исполняемый скрипт `my-script` в `usr/bin/`:

```bash
mkdir -p my-package-1.0/usr/bin
nano my-package-1.0/usr/bin/my-script
```

Содержимое `my-script`:

```bash
#!/bin/bash
echo "Hello from my-package!"
```

Сделайте скрипт исполняемым:

```bash
chmod +x my-package-1.0/usr/bin/my-script
```

## 5. Скрипты установки/удаления (опционально)

Вы можете добавить скрипты, которые будут выполняться на разных этапах установки или удаления пакета. Эти скрипты размещаются в директории `DEBIAN/` и должны быть исполняемыми.

Примеры скриптов:
*   `preinst`: Выполняется перед установкой пакета.
*   `postinst`: Выполняется после установки пакета.
*   `prerm`: Выполняется перед удалением пакета.
*   `postrm`: Выполняется после удаления пакета.

Например, `my-package-1.0/DEBIAN/postinst`:

```bash
#!/bin/bash
echo "my-package has been installed!"
```

Сделайте скрипт исполняемым:

```bash
chmod +x my-package-1.0/DEBIAN/postinst
```

## 6. Сборка пакета

После того как структура директорий и файлы готовы, можно собрать пакет с помощью `dpkg-deb`:

```bash
dpkg-deb --build my-package-1.0
```

В результате будет создан файл `my-package-1.0.deb` (или `my-package_1.0_amd64.deb` в зависимости от имени директории и архитектуры, указанной в `control`).

## 7. Установка и проверка пакета

Вы можете установить созданный пакет для проверки:

```bash
sudo dpkg -i my-package-1.0.deb
```

После установки вы сможете выполнить ваш скрипт:

```bash
my-script
```

И проверить статус пакета:

```bash
dpkg -l my-package
```

Для удаления пакета:

```bash
sudo dpkg -r my-package
```

---
**Связанные темы:**
*   [Управление пакетами в Linux: RPM и DEB](./rpm_and_deb_packages.md)
*   [Создание приватного Apt-репозитория с помощью reprepro](../private_apt_repository/private_apt_repository_with_reprepro.md)
*   [Управление приоритетами пакетов в Apt (Pinning)](./apt_pinning_and_priorities.md)