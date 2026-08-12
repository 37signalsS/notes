# OpenVAS / Greenbone (GVM) — установка и использование

**Greenbone Vulnerability Management (GVM)** — это мощный фреймворк с открытым исходным кодом для сканирования и управления уязвимостями. Он позволяет автоматизировать поиск проблем безопасности в сетевых узлах, веб-приложениях и инфраструктуре. Ранее проект был известен как **OpenVAS**, который теперь является одним из компонентов системы.

## Определения

*   **Greenbone Vulnerability Management (GVM)** — центральная архитектура, объединяющая компоненты сканирования, хранения данных и интерфейсы управления.
*   **OpenVAS (Open Vulnerability Assessment System)** — основной сканирующий движок, выполняющий тесты на уязвимости (NVT).
*   **Greenbone Security Assistant (GSA)** — веб-интерфейс (сервис `gsad`) для управления задачами и анализа отчетов.
*   **Greenbone Vulnerability Manager (GVMD)** — сервис управления, отвечающий за логику сканирования и хранение данных в PostgreSQL.
*   **NVT (Network Vulnerability Tests)** — скрипты проверок на наличие уязвимостей.
*   **Feeds (Фиды)** — обновляемые потоки данных об уязвимостях (NVT, SCAP, CERT).

## Базовые концепции

GVM использует модульную архитектуру для обеспечения гибкости и масштабируемости:

1.  **Уровни управления:** GVMD координирует работу сканеров, управляет базой данных и обрабатывает запросы от веб-интерфейса GSA.
2.  **Уровень сканирования:** Модуль OpenVAS взаимодействует с целями сканирования. Обмен данными между GVMD и OpenVAS происходит через протокол OSP (Open Scanner Protocol).
3.  **Потоки данных:** Система полагается на регулярное обновление фидов. Без актуальных NVT сканер не сможет обнаружить новые угрозы.
4.  **Профили сканирования:** Наборы настроек, определяющие интенсивность, глубину и типы проверок (например, `Full and fast`, `Full and deep`).

## Практические сценарии

### 1. Системные требования

Для стабильной работы GVM, особенно в процессе синхронизации фидов и параллельного сканирования, рекомендуются следующие характеристики:

*   **Процессор:** 2 или более ядер (рекомендуется 4).
*   **ОЗУ:** Минимум 4 ГБ, рекомендуется 8 ГБ или больше.
*   **Дисковое пространство:** Минимум 20 ГБ, рекомендуется 60 ГБ для хранения фидов и истории отчетов.

### 2. Установка через Docker (рекомендуется для Ubuntu 24.04 и выше)

Docker является предпочтительным методом для новых систем, так как изолирует зависимости GVM от системных библиотек.

**Подготовка Docker:**

```bash
sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# → Docker установлен и запущен
```

**Развертывание GVM:**

```bash
mkdir ~/greenbone-community && cd ~/greenbone-community
curl -f -L https://greenbone.github.io/docs/latest/_static/compose.yaml -o compose.yaml
sudo docker compose -f compose.yaml -p greenbone-community-edition pull
sudo docker compose -f compose.yaml -p greenbone-community-edition up -d
# → Контейнеры запущены
```

**Настройка пароля администратора:**

```bash
sudo docker compose -f compose.yaml -p greenbone-community-edition exec -u gvmd gvmd gvmd --user=admin --new-password=YourSecurePassword
# → Пароль admin успешно изменен
```

### 3. Установка из PPA (для Ubuntu 22.04)

Метод с использованием PPA (Personal Package Archive) остается актуальным для Ubuntu 22.04 LTS.

**Шаг 1: Подготовка системы и PostgreSQL**

GVM использует PostgreSQL для хранения конфигураций и результатов.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install postgresql -y
# → PostgreSQL установлен
```

**Шаг 2: Установка пакетов GVM**

```bash
sudo add-apt-repository ppa:mrazavi/gvm -y
sudo apt update
sudo apt install gvm -y
# → Установлены gvmd, ospd-openvas, gsad
```

**Шаг 3: Настройка Notus-сканера**

```bash
sudo mkdir -p /var/lib/notus
sudo chown gvm:gvm /var/lib/notus
```

### 4. Синхронизация фидов (для PPA-установки)

Это критический этап, который может занять от 30 минут до нескольких часов. Не прерывайте процесс. Выполняется от имени пользователя `gvm`.

```bash
sudo -u gvm -g gvm greenbone-nvt-sync
sudo -u gvm -g gvm greenbone-feed-sync --type CERT
sudo -u gvm -g gvm greenbone-feed-sync --type SCAP
sudo -u gvm -g gvm greenbone-feed-sync --type GVMD_DATA
# → Фиды загружены и индексируются
```

### 5. Настройка сетевого доступа и веб-интерфейса

По умолчанию веб-интерфейс GSA доступен только на `127.0.0.1`. Для удаленного доступа необходимо изменить конфигурацию.

**Для PPA-установки:**
Отредактируйте файл `/etc/default/gsad`:
```bash
# Измените GSAD_ADDRESS на 0.0.0.0
GSAD_ADDRESS=0.0.0.0
```

**Запуск и проверка служб (PPA):**
```bash
sudo systemctl restart gsad gvmd ospd-openvas
systemctl status gsad gvmd ospd-openvas
# → Все службы должны иметь статус active (running)
```

### 6. Первичная настройка и использование

**Вход в систему:**
1.  Перейдите по адресу: `https://<IP_сервера>:9392`.
2.  Примите самоподписанный SSL-сертификат.
3.  Используйте учетные данные по умолчанию (для PPA): `admin` / `admin`. **Сразу смените пароль** в разделе `Administration` -> `Users`.

**Проверка статуса фидов:**
В веб-интерфейсе: `Administration` -> `Feed Status`. Дождитесь статуса **Current** для всех строк. Если статус **Update in progress**, сканирование может быть неполным или недоступным.

### 7. Проведение сканирования

Процесс состоит из определения цели и создания задачи.

**Создание цели (Target):**
*   Путь: `Scans` -> `Targets`.
*   Нажмите **New Target** (синий значок со звездочкой).
*   **Name:** Имя цели (например, `Internal Network`).
*   **Hosts:** IP-адреса, диапазоны (192.168.1.0/24) или домены.
*   Нажмите **Save**.

**Создание и запуск задачи (Task):**
*   Путь: `Scans` -> `Tasks`.
*   Нажмите **New Task**.
*   **Name:** Имя задачи.
*   **Scan Target:** Выберите созданную ранее цель.
*   **Scan Config:** Рекомендуется `Full and fast` для баланса скорости и качества.
*   Нажмите **Save**, затем кнопку **Start** (зеленый треугольник) в списке задач.

## Дополнительная информация

### Устранение неполадок

*   **Службы не запускаются (PPA):** Проверьте логи: `journalctl -u gvmd` или `journalctl -u ospd-openvas`. Часто причина в незавершенной инициализации базы данных PostgreSQL.
*   **Ошибка "Feed is out of date":** Проверьте доступ к интернету и повторите команды синхронизации из раздела 4. После синхронизации системе требуется время на индексацию.
*   **Веб-интерфейс недоступен:** Проверьте, не блокирует ли файрвол порт `9392` (`sudo ufw allow 9392/tcp`).
*   **Контейнеры Docker не стартуют:** Используйте `sudo docker compose logs` для диагностики. Убедитесь, что порты `80`, `443` или `9392` не заняты другими сервисами.

### См. также
*   [Greenbone Community Documentation](https://greenbone.github.io/docs/latest/)
*   [Управление уязвимостями (Vulnerability Management)](../../Linux/Security/vulnerability_management.md)
*   [Сканеры безопасности: Обзор](../security_tools.md)
*   [Обзор PostgreSQL](../../Databases/PostgreSQL/overview.md)
