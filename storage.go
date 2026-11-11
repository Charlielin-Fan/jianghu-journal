package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

const maxDataSize = 16 << 20

type Category struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Color string `json:"color"`
}

type Entry struct {
	ID       string `json:"id"`
	Date     string `json:"date"`
	Title    string `json:"title"`
	Kind     string `json:"kind"`
	Start    *int   `json:"start"`
	Minutes  int    `json:"minutes"`
	Category string `json:"category"`
	Notes    string `json:"notes"`
	Focus    bool   `json:"focus"`
	Done     bool   `json:"done"`
}

type Journal struct {
	Version    int        `json:"version"`
	Revision   int64      `json:"revision"`
	Categories []Category `json:"categories"`
	Entries    []Entry    `json:"entries"`
	WeeklyGoal int        `json:"weeklyGoal"`
}

func newJournal() Journal {
	return Journal{Version: 1, Entries: []Entry{}, Categories: []Category{
		{"work", "工作", "#455F80"}, {"study", "学习", "#3F705D"},
		{"exercise", "运动", "#8C651F"}, {"life", "生活", "#98574E"},
	}}
}

var (
	idPattern    = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)
	colorPattern = regexp.MustCompile(`^#[0-9A-Fa-f]{6}$`)
)

func (j Journal) validate() error {
	if j.Version != 1 || j.Revision < 0 || j.Entries == nil || j.Categories == nil ||
		len(j.Entries) > 40000 || len(j.Categories) > 100 || j.WeeklyGoal < 0 || j.WeeklyGoal > 7*1440 {
		return errors.New("行记版本或数据格式无效")
	}
	categories := make(map[string]bool)
	names := make(map[string]bool)
	for _, category := range j.Categories {
		name := strings.TrimSpace(category.Name)
		if !idPattern.MatchString(category.ID) || categories[category.ID] ||
			name == "" || names[name] || utf8.RuneCountInString(name) > 24 || !colorPattern.MatchString(category.Color) {
			return errors.New("分类名称、颜色或编号无效，分类名称不能重复")
		}
		categories[category.ID] = true
		names[name] = true
	}
	ids := make(map[string]bool)
	for _, e := range j.Entries {
		date, err := time.Parse("2006-01-02", e.Date)
		if err != nil || date.Year() < 1000 || date.Year() > 9999 || date.Format("2006-01-02") != e.Date {
			return errors.New("事项日期无效")
		}
		if !idPattern.MatchString(e.ID) || ids[e.ID] || strings.TrimSpace(e.Title) == "" ||
			utf8.RuneCountInString(e.Title) > 160 || utf8.RuneCountInString(e.Notes) > 2000 {
			return errors.New("事项名称、备注或编号无效")
		}
		if e.Kind != "plan" && e.Kind != "actual" || e.Category != "" && !categories[e.Category] ||
			e.Minutes < 1 || e.Minutes > 1440 || e.Start == nil && e.Kind != "actual" ||
			e.Start != nil && (*e.Start < 0 || *e.Start >= 1440) || e.Kind == "actual" && (e.Focus || e.Done) {
			return errors.New("事项类型、分类或时段无效")
		}
		ids[e.ID] = true
	}
	return nil
}

func decodeJournal(data []byte) (Journal, error) {
	var j Journal
	data = []byte(strings.TrimPrefix(string(data), "\uFEFF"))
	if len(data) > maxDataSize || !utf8.Valid(data) {
		return j, errors.New("文件过大或不是有效的 UTF-8 文件")
	}
	if err := json.Unmarshal(data, &j); err != nil {
		return j, errors.New("无法读取行记文件")
	}
	return j, j.validate()
}

func readJournal(path string) (Journal, error) {
	info, err := os.Stat(path)
	if err != nil {
		return Journal{}, err
	}
	if info.Size() > maxDataSize {
		return Journal{}, errors.New("行记文件过大")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return Journal{}, err
	}
	return decodeJournal(data)
}

func loadJournal(path string) (Journal, bool, error) {
	j, err := readJournal(path)
	if err == nil {
		return j, false, nil
	}
	backup, backupErr := readJournal(path + ".bak")
	if backupErr == nil {
		return backup, true, nil
	}
	if os.IsNotExist(err) && os.IsNotExist(backupErr) {
		j = newJournal()
		return j, false, saveJournal(path, j)
	}
	return Journal{}, false, fmt.Errorf("行记数据和自动备份均无法读取。原文件保留在：\n%s", filepath.Dir(path))
}

func saveJournal(path string, j Journal) error {
	if err := j.validate(); err != nil {
		return err
	}
	data, err := json.MarshalIndent(j, "", "  ")
	if err != nil {
		return err
	}
	if len(data) > maxDataSize {
		return errors.New("行记文件已达到容量上限，请先备份")
	}
	return writeAtomic(path, append(data, '\n'))
}

func writeAtomic(path string, data []byte) error {
	file, err := os.CreateTemp(filepath.Dir(path), ".journal-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	_, writeErr := file.Write(data)
	if writeErr == nil {
		writeErr = file.Sync()
	}
	closeErr := file.Close()
	if writeErr != nil {
		return writeErr
	}
	if closeErr != nil {
		return closeErr
	}
	return replaceFile(file.Name(), path)
}
