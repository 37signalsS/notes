# DNS Automation: PowerDNS, Route53, CloudFlare

## Определения

- **DNS Automation** — автоматизация управления DNS-записями через Ansible для обеспечения консистентности между инфраструктурой и DNS-разрешениями
- **PowerDNS** — open-source DNS-сервер с API для управления зонами и записями
- **Route53** — Managed DNS-сервис AWS с REST API и support для health checks
- **CloudFlare DNS** — Managed DNS-сервис CloudFlare с глобальной CDN-сетью
- **Dynamic DNS (DDNS)** — автоматическое обновление DNS-записей при изменении IP-адресов хостов
- **DNS as Code** — подход, при котором DNS-записи описываются в коде и применяются через CI/CD

---

## Почему это критично

10 совпадений по DNS в Ansible — только в контексте network equipment. Нет управления DNS-записями для Linux/веб-сервисов: "как автоматически обновить DNS при деплое на новые серверы?".

---

## Сценарий 1: PowerDNS через API

### Установка и настройка PowerDNS

```yaml
---
- name: PowerDNS installation and configuration
  hosts: dns_servers
  become: true
  vars:
    pdns_listen_port: 53
    pdns_api_port: 8081
    pdns_api_key: "{{ vault_pdns_api_key }}"
    pdns_backends:
      - gsqlite3
  tasks:
    - name: Install PowerDNS
      ansible.builtin.apt:
        name:
          - pdns-server
          - pdns-backend-gsqlite3
          - pdns-tools
        state: present
        update_cache: true

    - name: Configure PowerDNS
      ansible.builtin.template:
        src: templates/pdns.conf.j2
        dest: /etc/powerdns/pdns.conf
        mode: "0640"
        owner: pdns
        group: pdns
      notify: Restart powerdns

    - name: Enable and start PowerDNS
      ansible.builtin.systemd:
        name: pdns
        enabled: true
        state: started

    - name: Open firewall ports
      ansible.posix.firewalld:
        port: "{{ item }}"
        permanent: true
        state: enabled
      loop:
        - "53/tcp"
        - "53/udp"
        - "{{ pdns_api_port }}/tcp"

  handlers:
    - name: Restart powerdns
      ansible.builtin.systemd:
        name: pdns
        state: restarted
```

### Управление зонами через URI

```yaml
---
- name: DNS zone management via PowerDNS API
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    pdns_api_url: "http://dns.internal:8081"
    pdns_api_key: "{{ vault_pdns_api_key }}"
    pdns_server_id: "localhost"
  tasks:
    - name: Create zone
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones"
        method: POST
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          name: "example.com."
          kind: "native"
          nameservers:
            - "ns1.example.com."
            - "ns2.example.com."
          rrsets:
            - name: "ns1.example.com."
              type: "A"
              ttl: 3600
              records:
                - content: "10.0.0.1"
                  disabled: false
            - name: "ns2.example.com."
              type: "A"
              ttl: 3600
              records:
                - content: "10.0.0.2"
                  disabled: false
        status_code: 201
      delegate_to: localhost

    - name: Add A record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "web.example.com."
              type: "A"
              ttl: 300
              changetype: "REPLACE"
              records:
                - content: "10.0.1.10"
                  disabled: false
                - content: "10.0.1.11"
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add CNAME record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "app.example.com."
              type: "CNAME"
              ttl: 300
              changetype: "REPLACE"
              records:
                - content: "web.example.com."
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add MX record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "example.com."
              type: "MX"
              ttl: 3600
              changetype: "REPLACE"
              records:
                - content: "10 mx1.mail.example.com."
                  disabled: false
                - content: "20 mx2.mail.example.com."
                  disabled: false
        status_code: 200
      delegate_to: localhost
```

---

## Сценарий 2: AWS Route53

### Управление зонами и записями

```yaml
---
- name: Route53 DNS management
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    aws_profile: "production"
    aws_region: "us-east-1"
    hosted_zone_id: "Z1234567890ABC"
  module_defaults:
    group/amazon.aws:
      profile: "{{ aws_profile }}"
      region: "{{ aws_region }}"
  tasks:
    - name: Create hosted zone
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "example.com"
        type: SOA
        value: "ns1.example.com. admin.example.com. 2024011501 3600 900 604800 86400"
      delegate_to: localhost

    - name: Add A record
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "web.example.com"
        type: A
        value: "10.0.1.10"
        ttl: 300
        alias: false
      delegate_to: localhost

    - name: Add multiple A records (load balancer)
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "api.example.com"
        type: A
        value: "{{ item }}"
        ttl: 60
        alias: true
        alias_hosted_zone_id: "Z35SXDOTRQ7X7K"
      loop:
        - "dualstack.app-lb-123456.eu-central-1.elb.amazonaws.com"
      delegate_to: localhost

    - name: Add CNAME record
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "www.example.com"
        type: CNAME
        value: "example.com"
        ttl: 300
      delegate_to: localhost

    - name: Add MX record
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "example.com"
        type: MX
        value: "10 mail.example.com"
        ttl: 3600
      delegate_to: localhost

    - name: Add TXT record (SPF)
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "example.com"
        type: TXT
        value: '"v=spf1 include:_spf.google.com ~all"'
        ttl: 3600
      delegate_to: localhost

    - name: Add health check
      amazon.aws.route53_health_check:
        state: present
        ip_addr: "10.0.1.10"
        port: 443
        type: HTTPS
        resource_path: "/health"
        failure_threshold: 3
        request_interval: 30
        regions:
          - eu-west-1
          - us-east-1
          - ap-southeast-1
      register: health_check
      delegate_to: localhost

    - name: Add failover record with health check
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "app.example.com"
        type: A
        value: "10.0.1.10"
        ttl: 60
        alias: true
        alias_hosted_zone_id: "Z35SXDOTRQ7X7K"
        health_check: "{{ health_check.health_check.id }}"
        failover: PRIMARY
      delegate_to: localhost
```

### DNS-as-Code:declaring зону целиком

```yaml
---
# dns/zones/example.com.yml
# Декларативное описание всей DNS-зоны
zone: example.com
ttl: 3600
nameservers:
  - ns1.example.com
  - ns2.example.com

records:
  - name: ns1
    type: A
    value: "10.0.0.1"
    ttl: 3600

  - name: ns2
    type: A
    value: "10.0.0.2"
    ttl: 3600

  - name: web
    type: A
    value: "10.0.1.10"
    ttl: 300

  - name: api
    type: A
    value: "10.0.1.20"
    ttl: 60

  - name: www
    type: CNAME
    value: example.com
    ttl: 300

  - name: mail
    type: A
    value: "10.0.2.10"
    ttl: 3600

  - name: "@"
    type: MX
    value: "10 mail.example.com"
    ttl: 3600

  - name: "@"
    type: TXT
    value: '"v=spf1 include:_spf.google.com ~all"'
    ttl: 3600

  - name: "_dmarc"
    type: TXT
    value: '"v=DMARC1; p=reject; rua=mailto:dmarc@example.com"'
    ttl: 3600
```

```yaml
---
- name: Apply DNS zone from declarative file
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    dns_provider: "route53"  # route53 | cloudflare | pdns
  tasks:
    - name: Load zone definition
      ansible.builtin.include_vars:
        file: "dns/zones/{{ zone_name }}.yml"

    - name: Apply to Route53
      ansible.builtin.include_tasks: route53_apply.yml
      when: dns_provider == "route53"

    - name: Apply to CloudFlare
      ansible.builtin.include_tasks: cloudflare_apply.yml
      when: dns_provider == "cloudflare"

    - name: Apply to PowerDNS
      ansible.builtin.include_tasks: pdns_apply.yml
      when: dns_provider == "pdns"
```

---

## Сценарий 3: CloudFlare DNS

### Управление через API

```yaml
---
- name: CloudFlare DNS management
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    cf_api_token: "{{ vault_cf_api_token }}"
    cf_zone_id: "{{ vault_cf_zone_id }}"
    cf_zone: "example.com"
  tasks:
    - name: Add A record
      ansible.builtin.uri:
        url: "https://api.cloudflare.com/client/v4/zones/{{ cf_zone_id }}/dns_records"
        method: POST
        headers:
          Authorization: "Bearer {{ cf_api_token }}"
          Content-Type: "application/json"
        body_format: json
        body:
          type: A
          name: "web.example.com"
          content: "10.0.1.10"
          ttl: 300
          proxied: false
        status_code: 200
      register: cf_result

    - name: Add proxied record
      ansible.builtin.uri:
        url: "https://api.cloudflare.com/client/v4/zones/{{ cf_zone_id }}/dns_records"
        method: POST
        headers:
          Authorization: "Bearer {{ cf_api_token }}"
          Content-Type: "application/json"
        body_format: json
        body:
          type: A
          name: "app.example.com"
          content: "10.0.1.20"
          ttl: 1
          proxied: true
        status_code: 200

    - name: Add CNAME record
      ansible.builtin.uri:
        url: "https://api.cloudflare.com/client/v4/zones/{{ cf_zone_id }}/dns_records"
        method: POST
        headers:
          Authorization: "Bearer {{ cf_api_token }}"
          Content-Type: "application/json"
        body_format: json
        body:
          type: CNAME
          name: "www.example.com"
          content: "example.com"
          ttl: 300
          proxied: true
        status_code: 200

    - name: List all records
      ansible.builtin.uri:
        url: "https://api.cloudflare.com/client/v4/zones/{{ cf_zone_id }}/dns_records"
        method: GET
        headers:
          Authorization: "Bearer {{ cf_api_token }}"
        return_content: true
      register: cf_records

    - name: Display current records
      ansible.builtin.debug:
        msg: >-
          {% for r in cf_records.json.result %}
          {{ r.type }} {{ r.name }} -> {{ r.content }} (proxied: {{ r.proxied }})
          {% endfor %}
```

---

## Сценарий 4: Dynamic DNS из Dynamic Inventory

### Автоматическое обновление DNS при изменении инфраструктуры

```yaml
---
- name: Sync infrastructure to DNS
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    dns_provider: "route53"
    inventory_source: "aws_ec2"
  tasks:
    - name: Get current infrastructure from dynamic inventory
      ansible.builtin.command:
        cmd: "ansible-inventory -i inventory/{{ inventory_source }}.yml --list"
      register: inventory_data
      changed_when: false

    - name: Parse inventory for DNS records
      ansible.builtin.set_fact:
        dns_records: >-
          {% set records = [] %}
          {% for host in groups['all'] %}
          {% set hostvars_data = hostvars[host] %}
          {% if hostvars_data.dns_name is defined %}
          {% set records = records + [{
            'name': hostvars_data.dns_name,
            'type': 'A',
            'value': hostvars_data.ansible_host,
            'ttl': 300
          }] %}
          {% endif %}
          {% endfor %}
          {{ records }}

    - name: Apply DNS records to Route53
      amazon.aws.route53:
        state: present
        zone: "internal.example.com"
        record: "{{ item.name }}"
        type: "{{ item.type }}"
        value: "{{ item.value }}"
        ttl: "{{ item.ttl }}"
      loop: "{{ dns_records }}"
      delegate_to: localhost

    - name: Verify DNS resolution
      ansible.builtin.uri:
        url: "https://dns.google/resolve?name={{ item.name }}.internal.example.com&type=A"
        return_content: true
      register: dns_verify
      loop: "{{ dns_records }}"
      delegate_to: localhost
```

---

## Сценарий 5: DNS Health Checks и Failover

```yaml
---
- name: DNS failover and health monitoring
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    endpoints:
      - name: primary
        ip: "10.0.1.10"
        health_url: "https://primary.example.com/health"
        weight: 10
      - name: secondary
        ip: "10.0.2.10"
        health_url: "https://secondary.example.com/health"
        weight: 20
  tasks:
    - name: Check endpoint health
      ansible.builtin.uri:
        url: "{{ item.health_url }}"
        validate_certs: true
        return_content: false
        status_code: 200
      register: health_results
      loop: "{{ endpoints }}"
      ignore_errors: true

    - name: Build DNS records from healthy endpoints
      ansible.builtin.set_fact:
        healthy_endpoints: >-
          {% set healthy = [] %}
          {% for result in health_results.results %}
          {% if result.status == 200 %}
          {% set healthy = healthy + [endpoints[result.item_index]] %}
          {% endif %}
          {% endfor %}
          {{ healthy }}

    - name: Update weighted DNS
      amazon.aws.route53:
        state: present
        zone: "example.com"
        record: "app.example.com"
        type: A
        value: "{{ item.ip }}"
        ttl: 60
        alias: true
        alias_hosted_zone_id: "Z35SXDOTRQ7X7K"
        set_identifier: "{{ item.name }}"
        weighted_routing_policy:
          weight: "{{ item.weight }}"
        health_check: "{{ health_check.id }}"
      loop: "{{ healthy_endpoints }}"
      delegate_to: localhost
```

---

## Шаблон DNS-as-Code

```yaml
---
# dns/dns_policy.yml
# Политика управления DNS для организации

dns_providers:
  primary:
    provider: route53
    profile: production
    zone: example.com
  secondary:
    provider: cloudflare
    zone: example.com

defaults:
  ttl: 300
  auto_update: true
  health_check_enabled: true
  health_check_interval: 60

record_templates:
  web_server:
    type: A
    ttl: 60
    health_check:
      path: /health
      port: 443
      protocol: HTTPS

  api_server:
    type: A
    ttl: 30
    health_check:
      path: /api/health
      port: 443
      protocol: HTTPS
```

---

## Дополнительная информация

- [ansible_network_automation.md](ansible_network_automation.md) — DNS для сетевого оборудования
- [dynamic_inventory.md](dynamic_inventory.md) — интеграция DNS с инвентарем
- [ansible_security_best_practices.md](ansible_security_best_practices.md) — DNSSEC и безопасность
- [ansible-automation-platform-operations.md](ansible-automation-platform-operations.md) — централизованное управление
