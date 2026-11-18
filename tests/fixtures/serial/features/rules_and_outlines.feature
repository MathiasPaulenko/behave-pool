Feature: Rules and outlines with serial tags

  Rule: Mixed rule block

    @serial
    Scenario: serial inside rule
      Given a step that runs quickly

    Scenario: parallel inside rule
      Given a step that runs quickly

  Scenario Outline: Mixed examples
    Given a step that runs quickly

    @serial
    Examples: serial row
      | value |
      | one   |

    Examples: parallel row
      | value |
      | two   |

  @serial
  Rule: Fully serial rule block

    Scenario: serial rule child
      Given a step that runs quickly
