# TDD и BDD: Методологии разработки, управляемой тестированием

### Определения

- **TDD (Test-Driven Development)** — это методология разработки, при которой тесты пишутся **до** написания кода. Цикл TDD: Red (падающий тест) → Green (минимальный код для прохождения) → Refactor (улучшение кода).
- **BDD (Behavior-Driven Development)** — это расширение TDD, фокусирующееся на поведении системы с точки зрения бизнеса. Использует естественно-языковые сценарии (Given-When-Then), понятные всем участникам команды.

### Основные концепции

#### 1. TDD (Test-Driven Development)

- **Цикл Red-Green-Refactor:**

  ```
  RED (Красный): Написать тест, который падает.
  GREEN (Зеленый): Написать минимальный код для прохождения теста.
  REFACTOR (Рефакторинг): Улучшить код, сохраняя зеленые тесты.
  ```

- **Три закона TDD (Роберт Мартин):**
    1. Не пишите production-код, пока не напишете падающий тест.
    2. Не пишите больше теста, чем достаточно для падения.
    3. Не пишите больше production-кода, чем достаточно для прохождения теста.
- **Преимущества:** Высокое качество кода, 100% покрытие нового кода, живая документация, уверенность при рефакторинге, продуманный дизайн.
- **Антипаттерны TDD:** "The Liar" (ложный тест), "The Giant" (огромный тест), "The Mockery" (чрезмерное мокирование).

#### 2. BDD (Behavior-Driven Development)

- **Фокус:** На поведении системы с точки зрения бизнеса и пользователей.
- **Формат сценария (Gherkin):** Использует ключевые слова `Feature`, `Scenario`, `Given`, `When`, `Then`, `And/But`.
- **Пример сценария (Gherkin):**

  ```gherkin
  Feature: User Authentication
    Scenario: Successful login with valid credentials
      Given the user "john" exists with password "secret123"
      When the user logs in with username "john" and password "secret123"
      Then the user should be redirected to the dashboard
  ```

- **Инструменты BDD:** Cucumber (Java, JavaScript, Ruby), Behave (Python), SpecFlow (C#).

### Практические сценарии

#### 1. Пример TDD на Python (Калькулятор)

- **Red:** Написание падающего теста `assert add(2, 3) == 5`.
- **Green:** Создание минимальной функции `def add(a, b): return 5`.
- **Refactor:** Исправление на `def add(a, b): return a + b` и добавление новых тестов.

#### 2. Пример BDD для e-commerce (Корзина покупок)

Использование Gherkin для описания сценариев работы корзины: добавление продукта, оформление заказа.

```gherkin
Feature: Shopping Cart
  Scenario: Adding product to cart
    Given the user is on the product page for "Laptop"
    When they click "Add to Cart"
    Then the cart should contain 1 item
    And the cart total should be $1000
```

#### 3. Сравнение TDD и BDD

| Аспект       | TDD                                 | BDD                                        |
|--------------|-------------------------------------|--------------------------------------------|
| **Фокус**    | Работоспособность кода              | Бизнес-поведение системы                   |
| **Участники**| Разработчики                        | Разработчики, QA, бизнес-аналитики         |
| **Язык**     | Язык программирования               | Естественный язык (Given-When-Then)        |
| **Область**  | Unit-тесты                          | Integration/E2E тесты, приемочные сценарии |
| **Документация**| Техническая                       | Бизнес-документация                        |

### Дополнительная информация

#### Когда использовать TDD

- При разработке новых функций с четкими техническими требованиями.
- Для алгоритмов, сложных бизнес-логик, библиотек.
- Для рефакторинга legacy-кода, чтобы обеспечить его работоспособность.

#### Когда использовать BDD

- Для интеграционных и сквозных сценариев, user stories.
- В кросс-функциональных командах для улучшения коммуникации.
- Как инструмент живой документации, понятной всем стейкхолдерам.

#### Лучшие практики тестирования (применимо к TDD/BDD)

- **AAA Pattern (Arrange-Act-Assert):** Для структурирования тестов.
- **Один Assert на тест:** Или логически связанные.
- **Независимые тесты:** Не должны зависеть от порядка выполнения.
- **FIRST принципы:** Fast, Independent, Repeatable, Self-validating, Timely.

#### Внешние ресурсы

- [Test-Driven Development by Kent Beck](https://www.amazon.com/Test-Driven-Development-Kent-Beck/dp/0321146530)
- [Cucumber Documentation](https://cucumber.io/docs/guides/overview/)

#### Внешние связи

- **[CI-CD: Обзор пайплайна](../../CI-CD/ci_cd_overview.md)** — TDD/BDD является частью процесса непрерывной интеграции.
- **[Стратегии развертывания](../../CI-CD/Core_Concepts/deployment_strategies.md)** — после успешного тестирования код развертывается с использованием различных стратегий.
- **[Виды тестов: Unit, Integration, E2E](../../Testing/testing_types_unit_integration_e2e.md)** — применение TDD/BDD на разных уровнях тестирования
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — встраивание TDD/BDD в пайплайн
- **[Метрики покрытия](../../Testing/testing_coverage_metrics.md)** — 100% покрытие нового кода в TDD
