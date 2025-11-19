# Создание ВМ в Yandex.Cloud с помощью Terraform

Terraform позволяет декларативно описывать и создавать инфраструктуру в облачных провайдерах. Ниже приведены примеры создания виртуальной машины (ВМ) в Yandex.Cloud.

## 1. Описание ресурса

Для создания ВМ используется ресурс `yandex_compute_instance`.

### Пример 1: Общий шаблон

```hcl
# main.tf

resource "yandex_compute_instance" "app_server" {
  name        = "svc-app-1"
  hostname    = "app-1"
  platform_id = "standard-v2"

  resources {
    cores  = 2
    memory = 2
  }

  boot_disk {
    initialize_params {
      image_id = var.ubuntu_image_id # Рекомендуется использовать переменную
      size     = 20
      type     = "network-hdd"
    }
  }

  network_interface {
    subnet_id = var.default_subnet_id # Рекомендуется использовать переменную
    nat       = true # Назначить публичный IP-адрес
  }

  metadata = {
    user-data = file("path/to/cloud-init.yaml") # Путь к файлу cloud-init
  }
}
```

### Пример 2: Конкретная ВМ для Vault

Этот пример из практического сценария развертывания Vault.

```hcl
resource "yandex_compute_instance" "vault_1" {
  name     = "yc-svc-vault-1"
  hostname = "vault-1"

  resources {
    cores  = 2
    memory = 1 // Меньше памяти для тестового стенда
  }

  boot_disk {
    initialize_params {
      image_id = var.ubuntu_image_id
      size     = 20
      type     = "network-hdd"
    }
  }

  network_interface {
    subnet_id = var.default_subnet_id
    nat       = true // Временно включаем NAT для установки ПО
  }

  // user-data можно передавать и в простом текстовом виде
  metadata = {
    user-data = "#cloud-config\nusers:\n  - name: yc-user\n    groups: sudo\n    shell: /bin/bash\n    sudo: ['ALL=(ALL) NOPASSWD:ALL']\n    ssh-authorized-keys:\n      - ${file("~/.ssh/id_rsa.pub")}"
  }
}
```

### Основные параметры:
*   `name`: Имя ВМ в облачной консоли.
*   `hostname`: Имя хоста внутри операционной системы.
*   `platform_id`: Платформа виртуализации.
*   `resources`:
    *   `cores`: Количество vCPU.
    *   `memory`: Объем RAM (ГБ).
*   `boot_disk`:
    *   `image_id`: ID образа операционной системы.
    *   `size`: Размер диска (ГБ).
    *   `type`: Тип диска (`network-hdd`, `network-ssd`).
*   `network_interface`:
    *   `subnet_id`: ID подсети, к которой будет подключена ВМ.
    *   `nat`: Если `true`, ВМ будет назначен публичный IP-адрес.
*   `metadata`:
    *   `user-data`: Позволяет передать скрипт или конфигурацию `cloud-init` для автоматической настройки ВМ при первом запуске. Это предпочтительный способ для установки ПО или добавления SSH-ключей.

## 2. Изменение сетевого интерфейса (отключение NAT)

**Важно:** Изменение параметра `nat` (включение или отключение публичного IP-адреса) является критической операцией, которая **требует остановки виртуальной машины**.

Процесс должен быть следующим:
1.  Остановите ВМ через UI облака, CLI или API.
2.  Измените значение `nat = false` в вашем `.tf` файле.
3.  Выполните `terraform apply`. Terraform увидит, что ВМ остановлена, и сможет безопасно изменить конфигурацию сетевого интерфейса.
4.  Запустите ВМ.

## 3. Переменные

Для гибкости и переиспользуемости рекомендуется выносить значения, которые могут меняться, в переменные.

```hcl
# variables.tf

variable "ubuntu_image_id" {
  description = "ID of the Ubuntu image to use for VMs"
  type        = string
  default     = "fd822mv2q333a1l55j8k" # Пример для Ubuntu 20.04 LTS
}

variable "default_subnet_id" {
  description = "ID of the default subnet"
  type        = string
}
```

## 4. Процесс развертывания

Стандартный процесс применения конфигурации Terraform:

1.  **Инициализация:** `terraform init`
2.  **Форматирование и Валидация:** `terraform fmt` и `terraform validate`
3.  **Планирование:** `terraform plan -out=tfplan`
4.  **Применение:** `terraform apply "tfplan"`
