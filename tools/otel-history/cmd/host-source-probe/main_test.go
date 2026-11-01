package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func scr(t *testing.T, text string) scrape {
	t.Helper()
	s, e := parse([]byte(text))
	if e != nil {
		t.Fatal(e)
	}
	return s
}
func TestExactLabelsTypesAndStableConstants(t *testing.T) {
	body := "# HELP node_uname_info Identity\n# TYPE node_uname_info gauge\nnode_uname_info{nodename=\"socrat-2\"} 1\n"
	baseline := scr(t, body)
	if compare(baseline, baseline, baseline)["sourceCompatibilityPassed"] != true {
		t.Fatal("identical source failed")
	}
	changed := scr(t, strings.Replace(body, "socrat-2", "socrat-3", 1))
	result := compare(baseline, changed, baseline)
	if result["sourceCompatibilityPassed"] != false {
		t.Fatal("ordinary label change accepted")
	}
	data, _ := json.Marshal(result)
	if strings.Contains(string(data), "socrat-") {
		t.Fatal("raw label values leaked")
	}
	changed = scr(t, strings.Replace(body, "} 1", "} 0", 1))
	if compare(baseline, changed, baseline)["sourceCompatibilityPassed"] != false {
		t.Fatal("constant info value change accepted")
	}
	changed = scr(t, strings.Replace(body, "gauge", "counter", 1))
	if compare(baseline, changed, baseline)["sourceCompatibilityPassed"] != false {
		t.Fatal("family type change accepted")
	}
}
func TestGaugeChangesAreNotPretendedToBeSimultaneousSamples(t *testing.T) {
	a := scr(t, "# TYPE node_memory_MemFree_bytes gauge\nnode_memory_MemFree_bytes 3\n")
	b := scr(t, "# TYPE node_memory_MemFree_bytes gauge\nnode_memory_MemFree_bytes 2\n")
	if compare(a, b, a)["sourceCompatibilityPassed"] != true {
		t.Fatal("ordinary live gauge movement rejected")
	}
}
func TestSourceChurnIsReportedAndNotAnExcuseToDropStableSeries(t *testing.T) {
	before := scr(t, "metric{pod=\"stable\"} 1\nmetric{pod=\"old\"} 1\n")
	after := scr(t, "metric{pod=\"stable\"} 2\nmetric{pod=\"new\"} 1\n")
	candidate := scr(t, "metric{pod=\"stable\"} 3\nmetric{pod=\"new\"} 1\n")
	result := compare(before, candidate, after)
	if result["sourceCompatibilityPassed"] != true || result["volatileLegacySeries"] != 2 {
		t.Fatal("churn accounting incorrect")
	}
	missing := scr(t, "metric{pod=\"new\"} 3\n")
	if compare(before, missing, after)["sourceCompatibilityPassed"] != false {
		t.Fatal("stable series disappeared")
	}
}
func TestDuplicateOrExplicitTimestampFailsClosed(t *testing.T) {
	for _, body := range []string{"metric 1\nmetric 2\n", "metric 1 12345\n"} {
		if _, e := parse([]byte(body)); e == nil {
			t.Fatal("invalid source accepted")
		}
	}
}
