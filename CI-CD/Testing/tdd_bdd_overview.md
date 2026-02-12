# TDD и BDD: Методологии разработки

## Определения

**TDD (Test Driven Development)** — это методология разработки программного обеспечения, при которой написание тестов происходит **до** написания кода. Основной цикл: написать тест → убедиться, что он падает → написать минимальный код для прохождения теста → рефакторинг.

**BDD (Behavior Driven Development)** — расширение TDD, фокусирующееся на поведении системы с точки зрения бизнеса. Использует естественно-языковые сценарии для описания ожидаемого поведения, понятные всем стейкхолдерам.

## TDD (Test Driven Development)

### Цикл Red-Green-Refactor

```
┌─────────────────────────────────────────────────────────────┐
│                      RED (Красный)                          │
│  Написать тест, который падает                              │
│  Определяет ожидаемое поведение                             │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                     GREEN (Зеленый)                         │
│  Написать минимальный код для прохождения теста             │
│  Даже если код "грязный" или неоптимальный                  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    REFACTOR (Рефакторинг)                   │
│  Улучшить код, сохраняя зеленые тесты                       │
│  Удалить дублирование, улучшить читаемость                  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        └──────────────────────────────────────►
                                   (повтор)
```

### Три закона TDD (Uncle Bob)

1. **Не пиши production-код, пока не напишешь падающий тест**
2. **Не пиши больше теста, чем достаточно для падения** (compile error = fail)
3. **Не пиши больше production-кода, чем достаточно для прохождения теста**

### Преимущества TDD

| Преимущество | Описание |
|--------------|----------|
| **Качество кода** | Меньше багов, чистый код |
| **Покрытие тестами** | 100% покрытие нового кода |
| **Документация** | Тесты служат живой документацией |
| **Уверенность** | Смелый рефакторинг без страха |
| **Дизайн** | Модульный, тестируемый код |

### Пример TDD на Python

```python
# Шаг 1: RED - пишем падающий тест
# test_calculator.py
def test_add():
    assert add(2, 3) == 5  # NameError: name 'add' is not defined

# Шаг 2: GREEN - минимальный код
# calculator.py
def add(a, b):
    return 5  # "Обман" для прохождения теста

# Шаг 3: REFACTOR - улучшаем
# calculator.py
def add(a, b):
    return a + b  # Правильная реализация

# Добавляем новые тесты
def test_add_negative():
    assert add(-2, -3) == -5

def test_add_zero():
    assert add(0, 5) == 5
```

### Антипаттерны TDD

- **The Liar:** Тест проходит, но не проверяет то, что должен
- **Success Against All Odds:** Тест зависит от порядка выполнения
- **The Giant:** Один огромный тест вместо множества маленьких
- **The Mockery:** Чрезмерное использование моков
- **The Inspector:** Тест проверяет приватные детали реализации

## BDD (Behavior Driven Development)

### Основные концепции

BDD переводит фокус с "тестирования" на "спецификацию поведения", используя единый язык для всех участников процесса.

### Формат сценария (Gherkin)

```gherkin
Feature: User Authentication
  As a registered user
  I want to log in with my credentials
  So that I can access my personal account

  Scenario: Successful login with valid credentials
    Given the user "john" exists with password "secret123"
    When the user logs in with username "john" and password "secret123"
    Then the user should be redirected to the dashboard
    And the user should see a welcome message

  Scenario: Failed login with invalid password
    Given the user "john" exists with password "secret123"
    When the user logs in with username "john" and password "wrongpass"
    Then the user should see an error message "Invalid credentials"
    And the user should remain on the login page
```

### Ключевые слова Gherkin

| Ключевое слово | Назначение | Пример |
|----------------|------------|--------|
| **Feature** | Описание функциональности | Feature: User Login |
| **Scenario** | Конкретный пример поведения | Scenario: Valid login |
| **Given** | Предусловия, начальное состояние | Given user is registered |
| **When** | Действие/триггер | When user clicks login |
| **Then** | Ожидаемый результат | Then dashboard is shown |
| **And/But** | Дополнение к предыдущему шагу | And error message appears |
| **Background** | Общие предусловия для всех сценариев | Background: Given database is seeded |
| **Scenario Outline** | Параметризованные сценарии | Scenario Outline: Login with <username> |

### Пример BDD с Cucumber (Java)

```java
// Feature file: login.feature
Feature: Login functionality
  
  Scenario: Successful login
    Given the user is on the login page
    When they enter valid credentials
    Then they should be redirected to home page

// Step Definitions
public class LoginSteps {
    @Given("the user is on the login page")
    public void userOnLoginPage() {
        driver.get("/login");
    }
    
    @When("they enter valid credentials")
    public void enterValidCredentials() {
        loginPage.enterUsername("admin");
        loginPage.enterPassword("password");
        loginPage.clickLogin();
    }
    
    @Then("they should be redirected to home page")
    public void verifyHomePage() {
        assertEquals("/home", driver.getCurrentUrl());
    }
}
```

### Инструменты BDD

| Язык | Инструмент | Особенности |
|------|------------|-------------|
| **Java** | Cucumber, JBehave | Самые популярные, интеграция с CI/CD |
| **Python** | Behave, pytest-bdd | Простота использования |
| **JavaScript** | Cucumber.js, Jest-Cucumber | Фронтенд-фокус |
| **C#** | SpecFlow | Отличная интеграция с .NET |
| **Ruby** | Cucumber, RSpec | Классические инструменты |
| **Go** | Godog | Нативная поддержка Go |

## Сравнение TDD и BDD

| Аспект | TDD | BDD |
|--------|-----|-----|
| **Фокус** | Работоспособность кода | Бизнес-поведение системы |
| **Участники** | Разработчики | Разработчики, QA, бизнес-аналитики |
| **Язык** | Язык программирования | Естественный язык (Given-When-Then) |
| **Область** | Unit-тесты | Integration/E2E тесты |
| **Документация** | Техническая | Бизнес-документация |
| **Скорость** | Быстрая обратная связь | Медленнее, но понятнее |

## Практические сценарии

### Сценарий 1: Разработка API с TDD

```python
# test_api.py
class TestUserAPI:
    def test_create_user(self, client):
        # RED
        response = client.post('/users', json={
            'name': 'John Doe',
            'email': 'john@example.com'
        })
        assert response.status_code == 201
        assert response.json()['id'] is not None
    
    def test_create_user_invalid_email(self, client):
        response = client.post('/users', json={
            'name': 'John',
            'email': 'invalid-email'
        })
        assert response.status_code == 400

# api.py - GREEN + REFACTOR
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    
    if not validate_email(data.get('email')):
        return jsonify({'error': 'Invalid email'}), 400
    
    user = User.create(data['name'], data['email'])
    return jsonify({'id': user.id}), 201
```

### Сценарий 2: BDD для e-commerce

```gherkin
Feature: Shopping Cart
  
  Background:
    Given the store has products:
      | name    | price | stock |
      | Laptop  | 1000  | 5     |
      | Mouse   | 25    | 10    |
  
  Scenario: Adding product to cart
    Given the user is on the product page for "Laptop"
    When they click "Add to Cart"
    Then the cart should contain 1 item
    And the cart total should be $1000
  
  Scenario: Checkout with insufficient stock
    Given the user has 6 "Laptop" in cart
    When they proceed to checkout
    Then they should see error "Insufficient stock. Only 5 available."
```

## Рекомендации

### Когда использовать TDD

- Новые функции с четкими требованиями
- Алгоритмы и бизнес-логика
- Библиотеки и фреймворки
- Рефакторинг legacy-кода

### Когда использовать BDD

- Интеграционные сценарии
- User stories и acceptance criteria
- Кросс-функциональные команды
- Документация поведения системы

### Лучшие практики

1. **AAA Pattern (Arrange-Act-Assert)** для unit-тестов
2. **ONE Assert per test** (или логически связанные asserts)
3. **Независимые тесты** — не должны зависеть от порядка
4. **Быстрые тесты** — unit-тесты < 10ms
5. **Читаемые имена** — `test_should_calculate_total_with_discount`
6. **FIRST принципы:** Fast, Independent, Repeatable, Self-validating, Timely

## Дополнительная информация

- [Test-Driven Development by Kent Beck](https://www.amazon.com/Test-Driven-Development-Kent-Beck/dp/0321146530)
- [The RSpec Book (BDD)](https://pragprog.com/titles/achbd/the-rspec-book/)
- [Cucumber Documentation](https://cucumber.io/docs/guides/overview/)
- [Given-When-Then article by Martin Fowler](https://martinfowler.com/bliki/GivenWhenThen.html)
