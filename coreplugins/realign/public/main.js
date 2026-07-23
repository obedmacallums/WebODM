PluginsAPI.Map.willAddControls([
        'realign/build/Realign.js',
        'realign/build/Realign.css'
    ], function(args, Realign){
    var tasks = [];
    var ids = {};

    for (var i = 0; i < args.tiles.length; i++){
        var task = args.tiles[i].meta.task;
        if (!ids[task.id]){
            tasks.push(task);
            ids[task.id] = true;
        }
    }

    // La realineación opera sobre una única tarea en la vista (comparte georreferenciación).
    if (tasks.length === 1){
        args.map.addControl(new Realign({map: args.map, tasks: tasks, tiles: args.tiles}));
    }
});
