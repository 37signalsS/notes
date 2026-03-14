# Kubespray: Offline установка — Шаг 1: Подготовка виртуальных серверов

## Инфраструктура

| Роль | IP | Назначение |
| :--- | :--- | :--- |
| pc-inet | 192.168.1.99 | Машина с интернетом |
| harbor | 192.168.1.100 | Harbor реестр |
| master-1-k8s | 192.168.1.101 | Control Plane + Ansible control |
| master-2-k8s | 192.168.1.102 | Control Plane |
| master-3-k8s | 192.168.1.103 | Control Plane |
| node-1-k8s | 192.168.1.104 | Worker |
| node-2-k8s | 192.168.1.105 | Worker |

## Автоматизация подготовки VM

Для подготовки узлов используется ansible-плейбук вместо ручной настройки.

### На pc-inet

**Клонирование репозитория:**

```bash
git clone https://github.com/ZM56/k8s-ans-bootstrap.git
```

### На master-1-k8s

**Создание SSH-ключа:**

```bash
ssh-keygen -t rsa
```

**Копирование ключа на все узлы:**

```bash
ssh-copy-id admin@192.168.1.102
ssh-copy-id admin@192.168.1.103
ssh-copy-id admin@192.168.1.104
ssh-copy-id admin@192.168.1.105
```

### Запуск плейбука подготовки

```bash
cd k8s-ans-bootstrap

# Отредактировать inventory и group_vars под свою инфраструктуру
ansible-playbook -i inventory.ini play.yml -u admin
```

## Требования к виртуальным машинам

### Минимальная конфигурация

| Роль | CPU | RAM | SSD | ОС |
| :--- | :--- | :--- | :--- | :--- |
| **pc-inet** | 2 | 4GB | 20GB | Ubuntu 24.04 |
| **harbor** | 2 | 4GB | 50GB | Ubuntu 24.04 |
| **master-1/2/3** | 2 | 4GB | 50GB | Ubuntu 24.04 |
| **node-1/2** | 4 | 8GB | 100GB | Ubuntu 24.04 |

### Предварительные требования к узлам

Перед запуском ansible-плейбука убедитесь, что на всех узлах:

1. **Установлена Ubuntu 24.04** на все хосты
2. **Настроен SSH доступ** с master-1 к воркерам
3. **Пользователь с root правами** (в примере `admin`)
4. **Отключен Swap:**

   ```bash
   sudo swapoff -a
   # Закомментировать строку о swap в /etc/fstab
   ```

5. **Отключен Firewall:**

   ```bash
   sudo systemctl stop firewalld
   sudo systemctl disable firewalld
   ```

6. **Отключен SELinux:**

   ```bash
   sudo setenforce 0
   # Отключить навсегда в /etc/selinux/config
   ```

## Проверка после подготовки

**Проверка SSH доступа:**

```bash
# С master-1-k8s
ssh admin@192.168.1.102 "hostname"
ssh admin@192.168.1.103 "hostname"
ssh admin@192.168.1.104 "hostname"
ssh admin@192.168.1.105 "hostname"
```

**Проверка sudo доступа:**

```bash
ssh admin@192.168.1.102 "sudo whoami"  # Должен вернуть root
```

## Связанные документы

- **[Определения](./offline_definitions.md)** — базовые термины
- **[Основные концепции](./offline_concepts.md)** — принципы offline-установки
- **[Шаг 2: Подготовка окружения с интернетом](./step2_internet_env.md)** — загрузка артефактов
- **[Kubespray: Установка](../kubespray_install/basic_concepts.md)** — базовая установка

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
