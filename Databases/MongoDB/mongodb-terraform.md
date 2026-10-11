# MongoDB: Infrastructure as Code (Terraform + Ansible)

**Актуально для:** MongoDB 8.0.x (последний патч 8.0.34, 24 сентября 2026 года), Terraform 1.16.x (последний 1.16.4, 23 сентября 2026 года), ansible-core 2.21.x, community.mongodb collection 1.8.0

---

## Определения

*   **Infrastructure as Code (IaC):** Подход, при котором инфраструктура (серверы, сеть) описывается декларативно в коде, версионируется в Git и применяется автоматически.
*   **Terraform:** Инструмент IaC для провижининга ресурсов (VM, сеть, диски) через провайдеров (AWS, Azure, GCP, OpenStack, vSphere).
*   **MongoDB Atlas Terraform Provider:** Официальный провайдер `mongodb/mongodb-atlas` — управляет **только** Atlas-кластерами (облачный SaaS, вне scope этой базы). Для self-managed MongoDB официального Terraform-провайдера **нет**.
*   **Ansible:** Инструмент конфигурационного управления (Configuration as Code). Для MongoDB существует коллекция `community.mongodb` (модули `mongodb_user`, `mongodb_replica_set`, `mongodb_shard` и др.).
*   **Разделение ответственности:** Terraform создаёт «железо» (VM, security groups, диски), Ansible настраивает ПО (установка `mongod`, replica set, пользователи, бэкапы).

---

## Базовые концепции

### Почему нет «Terraform для MongoDB» (self-managed)

*   MongoDB не выпускает официальный провайдер для self-managed кластеров — управление состоянием БД (репликация, шардирование, пользователи) требует императивной логики, которую Terraform не обеспечивает.
*   Атлас-провайдер (`mongodb/mongodb-atlas`) покрывает только облачный Atlas.
*   Стандартный паттерн self-managed: **Terraform → VM/сеть → Ansible → MongoDB**.

### Архитектура пайплайна

```
Terraform (plan/apply)
   ├─ VPC / subnets / security groups
   ├─ 3× VM (m5.xlarge, EBS gp3 500GB)
   └─ inventory → Ansible
                  ├─ установка mongodb-org 8.0
                  ├─ конфигурация mongod.conf
                  ├─ инициализация replica set
                  └─ создание пользователей (community.mongodb)
```

**Разделение ответственности по средам:**
*   **Terraform:** VM, security groups, диски, подсети, бэкенд-стейт (S3/GCS), IAM-роли для Ansible.
*   **Ansible:** Установка и конфигурация `mongod`/`mongos`, инициализация RS/шардов, пользователи, индексы, бэкапы, мониторинг-agent.
*   **Кто не отвечает за что:** Terraform не управляет состоянием MongoDB (RS, пользователи, индексы); Ansible не управляет инфраструктурой (VM, сеть).

**Ключевые принципы:**
*   **Декларативность Terraform:** Описание *конечного* состояния инфраструктуры, а не последовательности действий. `terraform plan` показывает разницу между описанным и реальным состоянием.
*   **Idempotency Ansible:** Модули `community.mongodb` идемпотентны — повторное применение не меняет состояние. `shell`/`command`-модули не идемпотентны по умолчанию; используйте `creates`/`creates` или модули.
*   **Версионирование:** `required_providers` с фиксированной версией предотвращает неожиданные изменения при обновлении провайдеров. `community.mongodb` — отдельная версия, обновляется через `ansible-galaxy`.

---

## Практические сценарии

### 1. Terraform: провижининг инфраструктуры (пример AWS)

```hcl
# main.tf
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = "eu-central-1"
}

resource "aws_security_group" "mongodb" {
  name        = "mongodb-sg"
  description = "MongoDB replica set"

  ingress {
    from_port   = 27017
    to_port     = 27017
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"] # Только внутренняя сеть
  }

  ingress {
    from_port   = 28017
    to_port     = 28017
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"] # HTTP-интерфейс (опционально)
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "mongodb" {
  count         = 3
  ami           = "ami-0abcdef1234567890" # Ubuntu 24.04
  instance_type = "m5.xlarge"

  root_block_device {
    volume_type = "gp3"
    volume_size = 500
    encrypted   = true
  }

  vpc_security_group_ids = [aws_security_group.mongodb.id]
  subnet_id              = "subnet-0123456789abcdef0"

  tags = {
    Name        = "mongo-${count.index}"
    Role        = "mongodb"
    Environment = "production"
  }
}

# Передача inventory в Ansible
resource "local_file" "ansible_inventory" {
  content = templatefile("${path.module}/inventory.tftpl", {
    hosts = aws_instance.mongodb[*].private_ip
  })
  filename = "${path.module}/inventory.ini"
}
```

```ini
# inventory.tftpl
[mongodb]
%{ for ip in hosts ~}
${ip} ansible_user=ubuntu
%{ endfor ~}

[mongodb:vars]
ansible_ssh_private_key_file=~/.ssh/mongodb.pem
```

```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
# → Apply complete! Resources: 5 added, 0 changed, 0 destroyed.
```

### 2. Ansible: конфигурация MongoDB

Полный playbook развёртывания см. в **[Ansible: setup MongoDB](../../Ansible/examples/mongodb_setup.md)** (759 строк: установка, replica set, шардирование, бэкапы). Ключевые шаги:

```yaml
# mongodb-config.yml
- name: Configure MongoDB replica set
  hosts: mongodb
  become: true
  roles:
    - role: community.mongodb.mongodb_repo   # репозиторий mongodb-org 8.0
    - role: community.mongodb.mongodb_install # установка пакетов
    - role: community.mongodb.mongodb_config  # /etc/mongod.conf
    - role: community.mongodb.mongodb_service # запуск mongod

- name: Init replica set and users
  hosts: mongo1
  roles:
    - role: community.mongodb.mongodb_replica_set
      vars:
        replica_set_name: rs0
        members:
          - { id: 0, host: "mongo1:27017" }
          - { id: 1, host: "mongo2:27017" }
          - { id: 2, host: "mongo3:27017" }

- name: Create application user
  hosts: mongo1
  tasks:
    - name: Create app user
      community.mongodb.mongodb_user:
        login_user: "{{ mongo_admin_user }}"
        login_password: "{{ vault_mongo_admin_password }}"
        database: admin
        user: app_user
        password: "{{ vault_app_password }}"
        roles:
          - { role: readWrite, db: sales_db }
        state: present
```

### 3. CI/CD интеграция

```yaml
# .gitlab-ci.yml (фрагмент)
terraform-plan:
  stage: plan
  image: hashicorp/terraform:1.16
  script:
    - terraform init -backend-config="bucket=my-tfstate"
    - terraform plan -out=tfplan
  artifacts:
    paths: [tfplan]

terraform-apply:
  stage: apply
  image: hashicorp/terraform:1.16
  script:
    - terraform apply -auto-approve tfplan
  when: manual

ansible-configure:
  stage: deploy
  image: ansible/ansible:latest
  script:
    - ansible-playbook -i inventory.ini mongodb-config.yml
  dependencies: [terraform-apply]
```

### 4. State и drift

```bash
# Проверка drift (расхождение реальной инфраструктуры с кодом)
terraform plan
# → No changes. Your infrastructure matches the configuration.

# Импорт существующего ресурса в state
terraform import aws_instance.mongodb[0] i-0123456789abcdef0
```

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`terraform plan` показывает деструктивные изменения** | Изменение AMI или instance_type без `create_before_destroy`. | `terraform plan` вывод. | Добавить `lifecycle { create_before_destroy = true }` или принять замену. |
| **Ansible: `module community.mongodb.mongodb_user not found`** | Коллекция не установлена. | `ansible-galaxy collection list community.mongodb`. | `ansible-galaxy collection install community.mongodb`. |
| **Replica set не инициализируется** | Ansible запущен до готовности `mongod` или неверные hostname в `members`. | `ansible mongodb -m shell -a "mongosh --eval 'rs.status()'"`. | Добавить `wait_for` порт 27017; использовать FQDN/private IP в `members[].host`. |
| **`state file` повреждён/утерян** | Ручное редактирование или потеря backend. | `terraform state list`. | Восстановить из backend (S3/GCS); при потере — `terraform import` ресурсов. |
| **Security group блокирует репликацию** | Ingress только на 27017, но RS-трафик идёт по тому же порту — ок; проблема в CIDR. | `aws ec2 describe-security-groups`. | Разрешить 27017 между всеми узлами RS (внутренний CIDR). |
| **Drift между Terraform и Ansible** | Ручные изменения на VM (не через Ansible). | `terraform plan` + `ansible --check`. | Запретить ручной доступ; всё через пайплайн. |

---

## Ограничения и Edge Cases

*   **Terraform не управляет состоянием MongoDB:** Replica set, пользователей, индексы — только Ansible (или Operator в Kubernetes).
*   **Atlas-провайдер:** `mongodb/mongodb-atlas` — для Atlas (облако), не для self-managed. Не путать.
*   **Idempotency Ansible:** Модули `community.mongodb` идемпотентны; shell-команды (`mongosh --eval`) — нет. Предпочитать модули.
*   **Secrets:** Пароли MongoDB — через Ansible Vault / Terraform variables (sensitive) / Vault, не в plaintext.
*   **Destroy:** `terraform destroy` удалит VM, но не данные на дисках (если не `destroy` volumes). Для полного удаления — явно удалять EBS/volumes.

---

## Дополнительная информация

*   **[Ansible: setup MongoDB](../../Ansible/examples/mongodb_setup.md)** — полный playbook развёртывания.
*   **[Ansible: модули БД](../../Ansible/Modules/ansible_database_modules.md)** — `community.mongodb` модули.
*   **[Operator для Kubernetes](./mongodb_operator.md)** — альтернатива Ansible в K8s.
*   **[Администрирование](./mongodb-administration.md)** — операции после развёртывания.
*   **[Высокая доступность](./high_availability.md)** — архитектура RS.
