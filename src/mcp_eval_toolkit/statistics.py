"""Case-cluster bootstrap; repeats are never treated as independent cases."""

import random
from statistics import mean


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def paired_summary(pairs: list[tuple[list[bool], list[bool]]], draws=5000, seed=0) -> dict:
    if draws < 100 or not pairs:
        raise ValueError("need at least one complete case and 100 bootstrap draws")
    if any(not a or len(a) != len(b) for a, b in pairs):
        raise ValueError("each case must have equal nonzero A/B repeat counts")
    a_means = [mean(a) for a, _ in pairs]
    b_means = [mean(b) for _, b in pairs]
    differences = [b - a for a, b in zip(a_means, b_means, strict=True)]
    summary = {
        "cases": len(pairs),
        "attempts_per_variant": sum(len(a) for a, _ in pairs),
        "a_rate": mean(a_means),
        "b_rate": mean(b_means),
        "delta": mean(differences),
        "a_interval": None,
        "b_interval": None,
        "delta_interval": None,
        "method": "95% percentile bootstrap over paired case clusters; repeats stay together",
        "seed": seed,
        "draws": draws,
    }
    if len(pairs) < 2:
        summary["limitation"] = "one case cannot estimate between-case uncertainty"
        return summary
    rng = random.Random(seed)
    a_samples, b_samples, delta_samples = [], [], []
    for _ in range(draws):
        indices = rng.choices(range(len(pairs)), k=len(pairs))
        a_samples.append(mean(a_means[i] for i in indices))
        b_samples.append(mean(b_means[i] for i in indices))
        delta_samples.append(mean(differences[i] for i in indices))
    for name, samples in (("a", a_samples), ("b", b_samples), ("delta", delta_samples)):
        summary[f"{name}_interval"] = [percentile(samples, 0.025), percentile(samples, 0.975)]
    summary["limitation"] = (
        "Conditional on this authored case set; small or homogeneous suites can yield degenerate intervals. Not evidence of broad generalization."
    )
    return summary
