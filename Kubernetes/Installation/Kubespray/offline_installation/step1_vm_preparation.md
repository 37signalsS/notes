# Kubespray: Offline установка — Шаг 1: Подготовка виртуальных серверов

## Определения

**VM Preparation** — процесс настройки виртуальных машин перед развёртыванием Kubernetes: выделение ресурсов, установка ОС, настройка SSH и отключение конфликтующих служб.

**k8s-ans-bootstrap** — вспомогательный Ansible-плейбук для автоматизации подготовки узлов кластера.

---

## Основные концепции

### Инфраструктура offline-кластера

Информация о ролях узлов и IP-адресах приведена в [практических сценариях offline-установки](./offline_practical.md#Инфраструктура).

### Минимальная конфигурация VM

| Роль | CPU | RAM | SSD | ОС |
| :--- | :--- | :--- | :--- | :--- |
| **pc-inet** | 2 | 4GB | 20GB | Ubuntu 24.04 |
| **harbor** | 2 | 4GB | 50GB | Ubuntu 24.04 |
| **master-1/2/3** | 2 | 4GB | 50GB | Ubuntu 24.04 |
| **node-1/2** | 4 | 8GB | 100GB | Ubuntu 24.04 |

### Предварительные требования

Перед запуском плейбука подготовки необходимо:

1. **Установлена Ubuntu 24.04** на все хосты
2. **Настроен SSH доступ** с master-1 к остальным узлам
3. **Пользователь с sudo правами** (в примере `admin`)

---

## Практические сценарии

### Автоматизация подготовки VM

Для подготовки узлов используется Ansible-плейбук вместо ручной настройки.

#### На pc-inet

**Клонирование репозитория:**

```bash
git clone https://github.com/ZM56/k8s-ans-bootstrap.git
```

#### На master-1-k8s

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

#### Запуск плейбука подготовки

```bash
cd k8s-ans-bootstrap

# Отредактировать inventory и group_vars под свою инфраструктуру
ansible-playbook -i inventory.ini play.yml -u admin
```

### Требования к узлам (выполняет плейбук)

Плейбук автоматически настраивает:

1. **Отключение Swap:**

   ```bash
   sudo swapoff -a
   # Закомментировать строку о swap в /etc/fstab
   ```

2. **Отключение Firewall:**

   ```bash
   sudo systemctl stop firewalld
   sudo systemctl disable firewalld
   ```

3. **Отключение SELinux:**

   ```bash
   sudo setenforce 0
   # Отключить навсегда в /etc/selinux/config
   ```

### Проверка после подготовки

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

---

## Дополнительная информация

### Связанные темы

Базовые термины описаны в [определениях offline-установки](./offline_definitions.md), принципы — в [основных концепциях](./offline_concepts.md). Следующий этап — [подготовка окружения с интернетом](./step2_internet_env.md). Общая информация по Kubespray — в [kubespray_install/basic_concepts.md](../kubespray_install/basic_concepts.md).
