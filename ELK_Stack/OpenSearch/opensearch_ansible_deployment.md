# Развертывание OpenSearch с помощью Ansible

## Определения

**Ansible-роль OpenSearch** — официальный инструмент автоматизации, предназначенный для развертывания, настройки и управления кластерами OpenSearch и OpenSearch Dashboards на операционных системах семейства Linux.

## Подготовка

### Требования к инфраструктуре

Для развертывания кластера из 3 узлов рекомендуются следующие минимальные ресурсы на каждую ноду:
- **CPU**: 2 ядра
- **RAM**: 8 ГБ
- **SSD**: 100 ГБ
- **ОС**: Ubuntu 22.04/24.04

### Предварительные условия

1. Установленный Ansible на управляющем сервере.
2. Настроенный SSH-доступ к узлам по ключам (без пароля) с правами `root` или возможностью `sudo`.

---

## Практические сценарии

### 1. Развертывание кластера

#### Шаг 1: Подготовка роли и инвентаря

Клонируйте официальный репозиторий с плейбуками:
```bash
git clone https://github.com/opensearch-project/ansible-playbook.git
cd ansible-playbook
```

Отредактируйте файл инвентаря `inventories/opensearch/hosts`. Пример конфигурации для 3 узлов данных/мастеров и одного узла для Dashboards:

```ini
os-node-1 ansible_host=10.0.1.1 ansible_user=root ip=10.0.1.1 roles=data,master
os-node-2 ansible_host=10.0.1.2 ansible_user=root ip=10.0.1.2 roles=data,master
os-node-3 ansible_host=10.0.1.3 ansible_user=root ip=10.0.1.3 roles=data,master

os-node-web ansible_host=10.0.1.4 ansible_user=root ip=10.0.1.4

[os-cluster]
os-node-1
os-node-2
os-node-3

[master]
os-node-1
os-node-2
os-node-3

[dashboards]
os-node-web
```

#### Шаг 2: Настройка переменных

Отредактируйте файл `inventories/opensearch/group_vars/all/all.yml`:

```yaml
os_cluster_name: "my-cluster"
os_version: "3.0.0"
os_dashboards_version: "3.0.0"

# Лимиты памяти Java (Heap Size)
xms_value: 2
xmx_value: 2

# Тип кластера: multi-node или single-node
cluster_type: multi-node

# Сохранение сертификатов (предотвращает их пересоздание при повторных запусках)
iac_enable: yes
```

#### Шаг 3: Запуск установки

Запустите плейбук, передав необходимые пароли через `extra-vars`. **Важно**: используйте сложные пароли, иначе кластер не запустится.

```bash
ansible-playbook -i inventories/opensearch/hosts opensearch.yml \
  --extra-vars "admin_password=YourStrongPassword123! kibanaserver_password=DashboardsPass789! logstash_password=LogstashPass456!" \
  --become
```

**Описание системных пользователей:**
- `admin_password`: полный доступ к API и веб-интерфейсу.
- `kibanaserver_password`: для внутреннего взаимодействия Dashboards с OpenSearch.
- `logstash_password`: для отправки данных из Logstash/Fluentd.

---

### 2. Балансировка нагрузки через Nginx

Для создания единой точки входа и обеспечения отказоустойчивости рекомендуется использовать Nginx перед узлами OpenSearch.

#### Конфигурация Nginx (на узле Dashboards)

Установите Nginx: `apt install nginx -y`. Пример конфигурации `/etc/nginx/nginx.conf`:

```nginx
events {
  worker_connections 1024;
}

http {
  upstream os_backend {
    server os-node-1.itzm.tech:9200;
    server os-node-2.itzm.tech:9200;
    server os-node-3.itzm.tech:9200;
    keepalive 15;
  }

  server {
    listen 9200 ssl;
    server_name os-node-web.itzm.tech;
    client_max_body_size 100M;

    # Пути к SSL-сертификатам
    ssl_certificate /etc/nginx/ssl/os-cert.crt;
    ssl_certificate_key /etc/nginx/ssl/os-key.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
      proxy_pass http://os_backend;
      proxy_read_timeout 5m;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
  }
}
```

Для работы балансировщика необходимо выпустить SSL-сертификаты и разместить их в `/etc/nginx/ssl/`. Если внутри OpenSearch включена обязательная проверка клиентских сертификатов, в секцию `location` необходимо добавить параметры `proxy_ssl_certificate` и `proxy_ssl_trusted_certificate`.

---

## Дополнительная информация

### Проверка состояния кластера

Доступ к OpenSearch Dashboards осуществляется по адресу `http://<IP-node-web>:5601`. Для проверки здоровья кластера используйте DevTools:

```http
GET _cluster/health
```

### См. также
- **[Обзор OpenSearch](./opensearch_overview.md)** — основные концепции и компоненты.
- **[Отказоустойчивость с Keepalived](./opensearch_high_availability_keepalived.md)** — настройка плавающего IP для кластера.
- **[Администрирование OpenSearch](./opensearch_administration.md)** — управление индексами и шардами.
