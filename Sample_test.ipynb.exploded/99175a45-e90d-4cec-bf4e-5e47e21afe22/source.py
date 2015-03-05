t = tabipy.Table(tabipy.TableHeaderRow('n', 'square'))
for n in range(1, 13):
    t.append_row((n, n**2))
t