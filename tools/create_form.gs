/**
 * Creates the Natak member-contribution Google Form and its responses sheet.
 *
 * Usage: paste into a new project at https://script.google.com, run
 * createNatakForm() once, and approve the permissions prompt. The execution
 * log prints the form URL, the responses sheet URL, and a FORM_CONFIG JSON
 * line (submit URL + field IDs) for generator.py's group build.
 *
 * Members don't fill this form directly: each group play page has its own
 * HTML form that posts here, showing existing values as read-only text. The
 * form stays single-page because direct posts only work for one page.
 *
 * Question titles map to Plays CSV columns (see COLUMN comments); the merge
 * Action relies on these titles, so change them in both places together.
 */
function createNatakForm() {
  var form = FormApp.create('Natak database: correct or add details');
  form.setDescription(
    'Share what you know about a play on the site: a correction or ' +
    'missing details. Submissions are reviewed before they appear.');
  form.setCollectEmail(false);

  var num = FormApp.createTextValidation()
    .requireNumber().setHelpText('Please enter a number.').build();
  var items = {};
  function text(key, title) { return items[key] = form.addTextItem().setTitle(title); }
  function para(key, title) { return items[key] = form.addParagraphTextItem().setTitle(title); }

  text('id', 'Play ID').setRequired(true);                    // COLUMN: ID
  text('title', 'Play title');                                // lookup only
  text('name', 'Your name').setRequired(true);
  text('email', 'Your email');                                // private
  text('acts', 'Number of acts').setValidation(num);          // COLUMN: Acts
  text('males', 'Male roles').setValidation(num);             // COLUMN: Males
  text('females', 'Female roles').setValidation(num);         // COLUMN: Females
  text('minutes', 'Duration (minutes)').setValidation(num);   // COLUMN: Length (in minutes)
  text('pages', 'Pages').setValidation(num);                  // COLUMN: Pages
  text('genre', 'Genre');                                     // COLUMN: Genre
  text('year_written', 'Year written').setValidation(num);    // COLUMN: Year of Writing
  text('year_performed', 'Year first performed').setValidation(num); // COLUMN: First Performance Year
  para('synopsis', 'Short synopsis');                         // COLUMN: Synopsis
  text('availability', 'Where to get the script');            // COLUMN: Availability
  items.how = form.addCheckboxItem().setTitle('How do you know this?')
    .setChoiceValues(['Performed in it', 'Read the script', 'From a book',
                      'From a website', 'General knowledge']);
  text('source', 'Source link');                              // COLUMN: Data Source
  para('notes', 'Corrections or other notes');                // COLUMN: Notes
  items.copy = form.addMultipleChoiceItem().setTitle('Do you have a copy of the script?')
    .setChoiceValues(['No', 'Yes, and it can be shared',
                      'Yes, but it is restricted (copyright)']);  // private
  para('contact', 'How to reach you about the script');       // private

  var ss = SpreadsheetApp.create('Natak form responses');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  // Field IDs ("entry.N") come from a pre-filled URL, one item at a time.
  var fields = {};
  Object.keys(items).forEach(function (key) {
    var item = items[key], resp;
    if (key === 'how') resp = item.createResponse(['General knowledge']);
    else if (key === 'copy') resp = item.createResponse('No');
    else resp = item.createResponse('1');
    var url = form.createResponse().withItemResponse(resp).toPrefilledUrl();
    fields[key] = 'entry.' + url.match(/entry\.(\d+)=/)[1];
  });
  var config = {
    action: form.getPublishedUrl().replace(/viewform.*$/, 'formResponse'),
    fields: fields
  };

  Logger.log('Form (edit): ' + form.getEditUrl());
  Logger.log('Responses sheet: ' + ss.getUrl());
  Logger.log('FORM_CONFIG: ' + JSON.stringify(config));
}
