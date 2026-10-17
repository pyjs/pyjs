from pyjs import js


@js
def catalog_source(component_id: str) -> str:
    if component_id == "accordion":
        return (
            "AccordionGroup(\n"
            "    AccordionItem('accessibility', 'Is it accessible?', 'Yes.', open=True),\n"
            "    AccordionItem('styling', 'Can it be styled?', 'Yes.'),\n"
            ")"
        )
    if component_id == "alert":
        return "Alert(AlertTitle('Heads up!'), AlertDescription('Your project is ready.'))"
    if component_id == "alert-dialog":
        return (
            "AlertDialog(\n"
            "    AlertDialogTrigger('Delete project'),\n"
            "    AlertDialogContent(\n"
            "        'Delete project',\n"
            "        AlertDialogTitle('Are you absolutely sure?'),\n"
            "        AlertDialogFooter(\n"
            "            AlertDialogCancel('Cancel'), AlertDialogAction('Continue')\n"
            "        ),\n"
            "    ),\n"
            ")"
        )
    if component_id == "aspect-ratio":
        return "AspectRatio(image, ratio='16 / 9')"
    if component_id == "attachment":
        return (
            "Attachment(\n"
            "    AttachmentMedia('PDF'),\n"
            "    AttachmentContent(\n"
            "        AttachmentTitle('design-notes.pdf'),\n"
            "        AttachmentDescription('240 KB · PDF'),\n"
            "    ),\n"
            ")"
        )
    if component_id == "avatar":
        return (
            "AvatarGroup(\n"
            "    Avatar(AvatarBadge(), fallback='AL', alt='Ada Lovelace'),\n"
            "    Avatar(fallback='GH', alt='Grace Hopper'),\n"
            "    AvatarGroupCount('+3'),\n"
            ")"
        )
    if component_id == "badge":
        return "Badge('Published', variant='secondary')"
    if component_id == "breadcrumb":
        return (
            "Breadcrumb(BreadcrumbList(\n"
            "    BreadcrumbItem(BreadcrumbLink('/', 'Home')),\n"
            "    BreadcrumbSeparator(),\n"
            "    BreadcrumbItem(BreadcrumbPage('Components')),\n"
            "))"
        )
    if component_id == "bubble":
        return (
            "BubbleGroup(\n"
            "    Bubble(BubbleContent('Can we ship this today?')),\n"
            "    Bubble(BubbleContent('Yes.'), align='end', variant='tinted'),\n"
            ")"
        )
    if component_id == "button":
        return "Button('Save changes', variant='outline')"
    if component_id == "button-group":
        return (
            "ButtonGroup(\n"
            "    Button('Back', variant='outline'),\n"
            "    ButtonGroupText('Page 2 of 8'),\n"
            "    Button('Next', variant='outline'),\n"
            ")"
        )
    if component_id == "calendar":
        return "Calendar('July', 2026, starts_on=3, selected_day=21)"
    if component_id == "card":
        return (
            "Card(\n"
            "    CardHeader(CardTitle('Team plan'), CardDescription('For teams.')),\n"
            "    CardContent('Unlimited projects and shared components.'),\n"
            "    CardFooter(Button('Choose plan')),\n"
            ")"
        )
    if component_id == "carousel":
        return "Carousel(CarouselItem(first_slide), CarouselItem(second_slide))"
    if component_id == "chart":
        return "LineChart([12, 18, 16, 29], ['Mon', 'Tue', 'Wed', 'Thu'])"
    if component_id == "collapsible":
        return (
            "Collapsible(\n"
            "    CollapsibleTrigger('Three deployment files'),\n"
            "    CollapsibleContent('app.py', 'pyproject.toml', 'README.md'),\n"
            ")"
        )
    if component_id == "combobox":
        return (
            "Combobox(\n"
            "    ComboboxItem('Python', 'Python'),\n"
            "    ComboboxItem('JavaScript', 'JavaScript'),\n"
            "    placeholder='Choose a language...',\n"
            ")"
        )
    if component_id == "command":
        return "Command(CommandItem('open', 'Open file'), CommandItem('save', 'Save all'))"
    if component_id == "context-menu":
        return (
            "ContextMenu(\n"
            "    ContextMenuTrigger(content),\n"
            "    ContextMenuContent(\n"
            "        ContextMenuItem('copy', 'Copy'),\n"
            "        ContextMenuItem('rename', 'Rename'),\n"
            "    ),\n"
            ")"
        )
    if component_id == "date-picker":
        return "DatePicker(Calendar('July', 2026, starts_on=3))"
    if component_id == "direction":
        return "Direction(content, direction='rtl')"
    if component_id == "drawer":
        return (
            "Drawer(\n"
            "    DrawerTrigger('Open drawer'),\n"
            "    DrawerContent('Account', DrawerTitle('Account')),\n"
            ")"
        )
    if component_id == "empty":
        return (
            "Empty(\n"
            "    EmptyHeader(EmptyTitle('No projects yet')),\n"
            "    EmptyContent(Button('Create project')),\n"
            ")"
        )
    if component_id == "forms":
        return (
            "FieldGroup(\n"
            "    Field(FieldLabel('Email'), Input(input_type='email')),\n"
            "    Field(FieldLabel('Biography'), Textarea()),\n"
            ")"
        )
    if component_id == "hover-card":
        return "HoverCard(HoverCardTrigger('@ada'), HoverCardContent(profile))"
    if component_id == "input-group":
        return "InputGroup(InputGroupAddon('https://'), InputGroupInput())"
    if component_id == "input-otp":
        return "InputOTP(6)"
    if component_id == "item":
        return (
            "Item(\n"
            "    ItemMedia('AL'),\n"
            "    ItemContent(ItemTitle('Ada Lovelace'), ItemDescription('Admin')),\n"
            "    variant='outline',\n"
            ")"
        )
    if component_id == "kbd":
        return "KbdGroup(Kbd('Ctrl'), '+', Kbd('K'))"
    if component_id == "marker":
        return "Marker(MarkerIcon('●'), MarkerContent('Live'))"
    if component_id == "menubar":
        return (
            "Menubar(\n"
            "    MenubarMenu('File', MenubarItem('new', 'New')),\n"
            "    MenubarMenu('Edit', MenubarItem('undo', 'Undo')),\n"
            ")"
        )
    if component_id == "message":
        return (
            "Message(\n"
            "    MessageContent(\n"
            "        MessageHeader('Ada · 2:14 PM'),\n"
            "        Bubble(BubbleContent('Ready to review.')),\n"
            "    )\n"
            ")"
        )
    if component_id == "message-scroller":
        return "MessageScroller(*messages)"
    if component_id == "native-select":
        return (
            "NativeSelect(\n"
            "    NativeSelectOption('comfortable', 'Comfortable', selected=True),\n"
            "    NativeSelectOption('compact', 'Compact'),\n"
            "    label='Density',\n"
            ")"
        )
    if component_id == "navigation-menu":
        return (
            "NavigationMenu(NavigationMenuList(\n"
            "    NavigationMenuLink('/', 'Overview', current=True),\n"
            "    NavigationMenuLink('/examples/', 'Examples'),\n"
            "))"
        )
    if component_id == "pagination":
        return (
            "Pagination(PaginationContent(\n"
            "    PaginationItem(PaginationPrevious('?page=1')),\n"
            "    PaginationItem(PaginationLink('?page=2', '2', current=True)),\n"
            "    PaginationItem(PaginationNext('?page=3')),\n"
            "))"
        )
    if component_id == "popover":
        return (
            "Popover(\n"
            "    PopoverTrigger('Open settings'),\n"
            "    PopoverContent(PopoverTitle('Dimensions'), fields),\n"
            ")"
        )
    if component_id == "progress":
        return "ProgressBar(66, 'File upload progress')"
    if component_id == "questionnaire":
        return (
            "Questionnaire(QuestionnaireItem(\n"
            "    'goal',\n"
            "    QuestionnaireTitle('What are you building?'),\n"
            "    QuestionnaireChoices(\n"
            "        QuestionnaireChoice('application', 'An application'),\n"
            "        QuestionnaireChoice('component', 'A reusable component'),\n"
            "    ),\n"
            "    required=True,\n"
            "))"
        )
    if component_id == "radio-group":
        return (
            "RadioGroup(\n"
            "    RadioGroupItem('comfortable', 'Comfortable', checked=True),\n"
            "    RadioGroupItem('compact', 'Compact'),\n"
            "    name='density',\n"
            ")"
        )
    if component_id == "resizable":
        return (
            "ResizablePanelGroup(\n"
            "    ResizablePanel('Navigation', initial_size=35),\n"
            "    ResizableHandle(with_handle=True),\n"
            "    ResizablePanel('Content', initial_size=65),\n"
            ")"
        )
    if component_id == "scroll-area":
        return "ScrollArea(*release_items, height='8rem')"
    if component_id == "select":
        return (
            "Select(\n"
            "    SelectTrigger('Choose a fruit'),\n"
            "    SelectContent(SelectItem('apple', 'Apple'), SelectItem('pear', 'Pear')),\n"
            ")"
        )
    if component_id == "separator":
        return "Separator('vertical', decorative=False)"
    if component_id == "sheet":
        return (
            "Sheet(\n"
            "    SheetTrigger('Edit profile'),\n"
            "    SheetContent(\n"
            "        'Edit profile', SheetHeader(SheetTitle('Edit profile')), fields,\n"
            "        SheetFooter(SheetClose('Save changes')), side='right',\n"
            "    ),\n"
            ")"
        )
    if component_id == "sidebar":
        return "Sidebar(navigation)"
    if component_id == "skeleton":
        return "Skeleton('100%', '0.875rem')"
    if component_id == "slider":
        return "Slider(45, minimum=0, maximum=100, label='Volume')"
    if component_id == "sonner":
        return "toaster.notify('Project saved', 'The latest changes are now live.')"
    if component_id == "spinner":
        return "Spinner(label='Saving')"
    if component_id == "table":
        return (
            "Table(\n"
            "    TableHeader(TableRow(TableHead('Invoice'), TableHead('Amount'))),\n"
            "    TableBody(TableRow(TableCell('INV001'), TableCell('$250.00'))),\n"
            ")"
        )
    if component_id == "tabs":
        return (
            "TabGroup(\n"
            "    Tab('account', 'Account', account_panel),\n"
            "    Tab('password', 'Password', password_panel),\n"
            "    default_value='account',\n"
            ")"
        )
    if component_id == "toggle":
        return "Toggle('Bold', pressed=True)"
    if component_id == "toggle-group":
        return (
            "ToggleGroup(\n"
            "    Toggle('Left', value='left'),\n"
            "    Toggle('Center', value='center', pressed=True),\n"
            "    Toggle('Right', value='right'),\n"
            ")"
        )
    if component_id == "tooltip":
        return "Tooltip(TooltipTrigger('?'), TooltipContent('Learn more'))"
    if component_id == "typography":
        return (
            "TypographyP(\n"
            "    'Run ', TypographyInlineCode('pyjs serve'), ' to begin.'\n"
            ")"
        )
    return ""
