function evaluate(ctx) {
  const assertions = ctx.experiment.itemExpectedOutput.assertions;
  const output = String(ctx.observation.output ?? "").trim();

  function check(assertion) {
    switch (assertion.type) {
      case "equals":
        return output === assertion.value;
      case "contains":
        return output.includes(assertion.value);
      case "regex":
        return new RegExp(assertion.value).test(output);
      case "not-regex":
        return !new RegExp(assertion.value).test(output);
      case "not-icontains":
        return !output.toLowerCase().includes(assertion.value.toLowerCase());
      case "not-icontains-any":
        return !assertion.value.some((value) =>
          output.toLowerCase().includes(value.toLowerCase()),
        );
      default:
        throw new Error(`Unsupported assertion type: ${assertion.type}`);
    }
  }

  const checked = assertions.map((assertion, index) => ({
    index,
    ...assertion,
    passed: check(assertion),
  }));
  const failed = checked.filter((assertion) => !assertion.passed);
  const metrics = [...new Set(checked.map((assertion) => assertion.metric))];

  return {
    scores: [
      {
        name: "pass",
        value: failed.length === 0,
        dataType: "BOOLEAN",
        comment: failed.length === 0 ? "All assertions passed" : JSON.stringify(failed),
        metadata: { failedAssertions: failed },
      },
      ...metrics.map((metric) => {
        const matching = checked.filter((assertion) => assertion.metric === metric);
        return {
          name: metric,
          value: matching.filter((assertion) => assertion.passed).length / matching.length,
          dataType: "NUMERIC",
          metadata: { failedAssertions: matching.filter((assertion) => !assertion.passed) },
        };
      }),
    ],
  };
}
