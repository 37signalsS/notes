# VPN Automation — Ansible и Terraform

## Определения

Автоматизация развертывания и управления VPN позволяет:
- Воспроизводить конфигурации (Infrastructure as Code)
- Масштабировать deployment (десятки/сотни серверов)
- Управлять ключами и сертификатами
- Автоматизировать ротацию ключей

> **См. также:** [WireGuard](./wireguard_practical.md), [OpenVPN](./openvpn.md), [IPsec](./ipsec/ipsec.md)

---

## Ansible

### Роль для WireGuard

```yaml
# roles/wireguard/tasks/main.yml
---
- name: Установка WireGuard
  apt:
    name: wireguard
    state: present
    update_cache: yes
  when: ansible_os_family == "Debian"

- name: Загрузка модуля wireguard
  modprobe:
    name: wireguard
    state: present

- name: Создание директории конфигурации
  file:
    path: /etc/wireguard
    state: directory
    mode: '0700'

- name: Генерация приватного ключа
  shell: wg genkey
  register: wg_private_key
  creates: /etc/wireguard/private.key

- name: Сохранение приватного ключа
  copy:
    content: "{{ wg_private_key.stdout }}"
    dest: /etc/wireguard/private.key
    mode: '0600'

- name: Получение публичного ключа
  shell: cat /etc/wireguard/private.key | wg pubkey
  register: wg_public_key

- name: Регистрация ключа в inventory
  set_fact:
    wireguard_public_key: "{{ wg_public_key.stdout }}"

- name: Генерация конфигурации wg0
  template:
    src: wg0.conf.j2
    dest: /etc/wireguard/wg0.conf
    mode: '0600'
  notify: restart wireguard

- name: Включение автозапуска
  systemd:
    name: "wg-quick@wg0"
    enabled: yes
    state: started
```

```yaml
# roles/wireguard/templates/wg0.conf.j2
[Interface]
PrivateKey = {{ lookup('file', '/etc/wireguard/private.key') }}
Address = {{ wireguard_address }}
ListenPort = {{ wireguard_port | default(51820) }}

{% for peer in wireguard_peers %}
[Peer]
PublicKey = {{ peer.public_key }}
AllowedIPs = {{ peer.allowed_ips | join(', ') }}
{% if peer.endpoint is defined %}
Endpoint = {{ peer.endpoint }}
{% endif %}
{% if peer.persistent_keepalive is defined %}
PersistentKeepalive = {{ peer.persistent_keepalive }}
{% endif %}
{% endfor %}
```

```yaml
# host_vars/server1.yml
wireguard_address: "10.0.0.1/24"
wireguard_port: 51820
wireguard_peers:
  - public_key: "{{ hostvars['server2']['wireguard_public_key'] }}"
    allowed_ips:
      - "10.0.0.2/32"
      - "192.168.2.0/24"
    endpoint: "203.0.113.2:51820"
  - public_key: "{{ hostvars['client1']['wireguard_public_key'] }}"
    allowed_ips:
      - "10.0.0.3/32"
    persistent_keepalive: 25
```

```yaml
# playbook.yml
---
- name: Deploy WireGuard VPN
  hosts: vpn_servers
  become: yes
  roles:
    - wireguard

- name: Gather WireGuard public keys
  hosts: all
  tasks:
    - name: Get public key
      command: cat /etc/wireguard/public.key
      register: pub_key
      changed_when: false

    - name: Set fact
      set_fact:
        wireguard_public_key: "{{ pub_key.stdout }}"
```

### Роль для OpenVPN

```yaml
# roles/openvpn/tasks/main.yml
---
- name: Установка OpenVPN и Easy-RSA
  apt:
    name:
      - openvpn
      - easy-rsa
    state: present
    update_cache: yes

- name: Инициализация PKI
  shell: |
    cd /etc/openvpn/easy-rsa
    ./easyrsa init-pki
    ./easyrsa build-ca nopass
  args:
    creates: /etc/openvpn/easy-rsa/pki/ca.crt

- name: Генерация tls-crypt ключа
  shell: openvpn --genkey secret /etc/openvpn/ta.key
  args:
    creates: /etc/openvpn/ta.key

- name: Генерация DH параметров
  shell: |
    cd /etc/openvpn/easy-rsa
    ./easyrsa gen-dh
  args:
    creates: /etc/openvpn/easy-rsa/pki/dh.pem

- name: Генерация серверного сертификата
  shell: |
    cd /etc/openvpn/easy-rsa
    ./easyrsa build-server-full server nopass
  args:
    creates: /etc/openvpn/easy-rsa/pki/issued/server.crt

- name: Копирование сертификатов
  copy:
    src: "/etc/openvpn/easy-rsa/pki/{{ item.src }}"
    dest: "/etc/openvpn/{{ item.dest }}"
    remote_src: yes
  loop:
    - { src: "ca.crt", dest: "ca.crt" }
    - { src: "issued/server.crt", dest: "server.crt" }
    - { src: "private/server.key", dest: "server.key" }
    - { src: "dh.pem", dest: "dh.pem" }

- name: Генерация конфигурации сервера
  template:
    src: server.conf.j2
    dest: /etc/openvpn/server.conf
  notify: restart openvpn

- name: Включение автозапуска
  systemd:
    name: openvpn@server
    enabled: yes
    state: started
```

### Роль для IPsec (strongSwan)

```yaml
# roles/ipsec/tasks/main.yml
---
- name: Установка strongSwan
  apt:
    name:
      - strongswan
      - libcharon-extra-plugins
    state: present
    update_cache: yes

- name: Генерация CA
  shell: |
    ipsec pki --gen --type rsa --size 4096 --outform pem > /etc/swanctl/private/ca.key
    ipsec pki --self --ca --lifetime 3650 --in /etc/swanctl/private/ca.key \
      --type rsa --dn "CN=VPN CA" --outform pem > /etc/swanctl/cacerts/ca.crt
  args:
    creates: /etc/swanctl/cacerts/ca.crt

- name: Генерация серверного ключа
  shell: |
    ipsec pki --gen --type rsa --size 4096 --outform pem > /etc/swanctl/private/server.key
  args:
    creates: /etc/swanctl/private/server.key

- name: Генерация серверного сертификата
  shell: |
    ipsec pki --pub --in /etc/swanctl/private/server.key --type rsa | \
      ipsec pki --issue --lifetime 3650 \
        --cacert /etc/swanctl/cacerts/ca.crt \
        --cakey /etc/swanctl/private/ca.key \
        --dn "CN={{ ansible_fqdn }}" \
        --san={{ ansible_fqdn }} \
        --outform pem > /etc/swanctl/certs/server.crt
  args:
    creates: /etc/swanctl/certs/server.crt

- name: Установка прав на ключи
  file:
    path: "{{ item }}"
    mode: '0600'
  loop:
    - /etc/swanctl/private/ca.key
    - /etc/swanctl/private/server.key

- name: Генерация конфигурации
  template:
    src: swanctl.conf.j2
    dest: /etc/swanctl/conf.d/vpn.conf
  notify: restart strongswan
```

---

## Terraform

### WireGuard (DHCP-провайдер)

```hcl
# main.tf
terraform {
  required_providers {
    dhcp = {
      source  = "hyperscoop/dhcp"
      version = "~> 0.1"
    }
  }
}

provider "dhcp" {
  host = "https://dhcp.example.com"
}

resource "dhcp_static_mapping" "vpn_client1" {
  subnet_id   = dhcp_subnet.vpn.id
  mac_address = "00:11:22:33:44:55"
  ip_address  = "10.0.0.10"
  hostname    = "vpn-client1"
}
```

### WireGuard через local-exec

```hcl
# main.tf
resource "null_resource" "wireguard_server" {
  triggers = {
    server_ip = var.server_ip
  }

  connection {
    type     = "ssh"
    host     = var.server_ip
    user     = "root"
    private_key = file("~/.ssh/id_rsa")
  }

  provisioner "remote-exec" {
    inline = [
      "apt-get update && apt-get install -y wireguard",
      "wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key",
      "chmod 600 /etc/wireguard/private.key",
    ]
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/wg0.conf.tpl", {
      private_key = data.external.wireguard_key.result.private_key
      address     = var.wireguard_address
      peers       = var.wireguard_peers
    })
    destination = "/etc/wireguard/wg0.conf"
  }

  provisioner "remote-exec" {
    inline = [
      "systemctl enable wg-quick@wg0",
      "systemctl start wg-quick@wg0",
    ]
  }
}
```

---

## GitOps для VPN

### FluxCD / ArgoCD

Для Kubernetes можно использовать GitOps для управления VPN:

```yaml
# wireguard-daemonset.yaml (в Git)
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: wireguard
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: wireguard
  template:
    metadata:
      labels:
        app: wireguard
    spec:
      hostNetwork: true
      containers:
        - name: wireguard
          image: linuxserver/wireguard:latest
          securityContext:
            privileged: true
          volumeMounts:
            - name: lib-modules
              mountPath: /lib/modules
              readOnly: true
      volumes:
        - name: lib-modules
          hostPath:
            path: /lib/modules
```

---

## Лучшие практики

1. **Хранение ключей:** Используйте Ansible Vault или HashiCorp Vault для хранения приватных ключей и PSK.

2. **Ротация ключей:** Автоматизируйте ротацию ключей через cron + Ansible:
   ```bash
   #!/bin/bash
   # /etc/cron.monthly/wireguard-key-rotate
   NEW_PRIVKEY=$(wg genkey)
   NEW_PUBKEY=$(echo "$NEW_PRIVKEY" | wg pubkey)
   
   # Обновление ключа на сервере
   echo "$NEW_PRIVKEY" > /etc/wireguard/private.key
   sudo wg set wg0 private-key /etc/wireguard/private.key
   
   # Рассылка нового публичного ключа клиентам
   ansible-playbook -i inventory rotate-wireguard-keys.yml
   ```

3. **Воспроизводимость:** Все конфигурации VPN должны быть в Git.

4. **Тестирование:** Используйте molecule (Ansible) или terratest (Terraform) для тестирования ролей.

---

## Дополнительная информация

### Связанные документы

- **[WireGuard](./wireguard_practical.md)** — настройка WireGuard
- **[OpenVPN](./openvpn.md)** — настройка OpenVPN
- **[IPsec](./ipsec/ipsec.md)** — настройка IPsec
- **[VPN в контейнерах](./vpn_in_containers.md)** — Docker и Kubernetes
