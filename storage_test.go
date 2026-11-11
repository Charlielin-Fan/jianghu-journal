package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestRecoverAndProtectFiles(t *testing.T) {
	path := filepath.Join(t.TempDir(), "数据记录.json")
	original, recovered, err := loadJournal(path)
	if err != nil || recovered {
		t.Fatalf("first launch: %v, %v", err, recovered)
	}
	original.Entries = append(original.Entries, Entry{
		ID: "entry-1", Date: "2028-02-29", Kind: "actual", Title: "灯火·清河🏮", Minutes: 40,
	})
	if err := saveJournal(path+".bak", original); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("{broken"), 0600); err != nil {
		t.Fatal(err)
	}
	recovery, recovered, err := loadJournal(path)
	if err != nil || !recovered || recovery.Entries[0].Title != original.Entries[0].Title {
		t.Fatalf("recovery: %v, %v, %#v", err, recovered, recovery)
	}
	if err := os.Remove(path + ".bak"); err != nil {
		t.Fatal(err)
	}
	if _, _, err := loadJournal(path); err == nil {
		t.Fatal("expected startup to fail when existing data is unreadable")
	}
	raw, err := os.ReadFile(path)
	if err != nil || string(raw) != "{broken" {
		t.Fatalf("unreadable file was changed: %q, %v", raw, err)
	}
}

func TestValidateAndDecode(t *testing.T) {
	j := newJournal()
	j.Entries = append(j.Entries, Entry{ID: "a", Date: "2028-02-29", Title: "测试", Kind: "actual", Minutes: 20})
	raw, err := json.Marshal(j)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := decodeJournal(append([]byte{0xEF, 0xBB, 0xBF}, raw...)); err != nil {
		t.Fatalf("valid UTF-8 BOM file: %v", err)
	}
	if _, err := decodeJournal([]byte{0xFF}); err == nil {
		t.Fatal("accepted invalid UTF-8")
	}
	for name, change := range map[string]func(*Journal){
		"non-leap day":       func(j *Journal) { j.Entries[0].Date = "2027-02-29" },
		"unknown category":   func(j *Journal) { j.Entries[0].Category = "missing" },
		"blank title":        func(j *Journal) { j.Entries[0].Title = " " },
		"duplicate id":       func(j *Journal) { j.Entries = append(j.Entries, j.Entries[0]) },
		"invalid duration":   func(j *Journal) { j.Entries[0].Minutes = 0 },
		"invalid start":      func(j *Journal) { start := 1440; j.Entries[0].Start = &start },
		"invalid plan":       func(j *Journal) { j.Entries[0].Kind = "plan" },
		"duplicate category": func(j *Journal) { j.Categories[1].Name = j.Categories[0].Name },
	} {
		t.Run(name, func(t *testing.T) {
			copy, err := decodeJournal(raw)
			if err != nil {
				t.Fatal(err)
			}
			change(&copy)
			if copy.validate() == nil {
				t.Fatal("accepted invalid journal")
			}
		})
	}
}

func TestConcurrentWritesProtectRevisions(t *testing.T) {
	s := &session{data: newJournal(), host: "127.0.0.1:7890", path: filepath.Join(t.TempDir(), "journal.json")}
	results := make(chan int, 2)
	var group sync.WaitGroup
	for _, title := range []string{"计划甲", "计划乙"} {
		group.Add(1)
		go func() {
			defer group.Done()
			j := newJournal()
			j.Entries = append(j.Entries, Entry{ID: "entry", Date: "2026-11-11", Title: title, Kind: "actual", Minutes: 30})
			raw, _ := json.Marshal(j)
			req := httptest.NewRequest(http.MethodPut, "/api/journal", strings.NewReader(string(raw)))
			req.Header.Set("Origin", "http://"+s.host)
			out := httptest.NewRecorder()
			s.write(out, req)
			results <- out.Code
		}()
	}
	group.Wait()
	close(results)
	count := map[int]int{}
	for code := range results {
		count[code]++
	}
	if count[http.StatusOK] != 1 || count[http.StatusConflict] != 1 {
		t.Fatalf("concurrent results: %v", count)
	}
	data, err := readJournal(s.path)
	if err != nil || len(data.Entries) != 1 || data.Revision != 1 {
		t.Fatalf("disk result: %v %#v", err, data)
	}
}
