# Fixture outline for the pptx-brand end-to-end test

## Q3 Business Review {layout=title}
Leadership update, October 2026

## Where we are {layout=section}
Three quarters in

## Highlights {layout=two_column icons="growth,shield" icon_color=primary}
### Growth
- Revenue up **14%** year on year
- Two new regions opened
### Security
- Zero critical findings
- Audit completed early

## Before and after {layout=comparison}
### Before
- Manual review
- Five day turnaround
### After
- Automated gate
- Same day

## Revenue by region {layout=chart}
```chart
{"type": "column", "title": "Revenue ($M)", "categories": ["NA", "EMEA", "APAC"],
 "series": [{"name": "2025", "values": [10, 7, 4]}, {"name": "2026", "values": [12, 8, 6]}]}
```
Notes: APAC is the story here.

## Risks {layout=table}
| Risk | Owner | Status |
|---|---|---|
| Vendor lock-in | CTO | Open |
| Hiring | HR | Mitigated |

## Platform {layout=image_left}
![cost](asset:coin)
One platform, one bill.

## Priorities for Q4
- Finish the platform migration and retire the legacy stack before the fiscal year closes
- Open the third region and hire the local leadership team ahead of launch
- Hold cloud spend flat while traffic grows by renegotiating committed-use discounts
- Ship the automated security gate to every product team, not only the pilot group
- Publish the customer trust report and refresh it every quarter from live data
- Reduce median support response time to under four hours across all tiers

## Thank you {layout=closing}
questions@example.com
